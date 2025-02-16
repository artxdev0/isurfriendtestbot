
import tomllib
import random
import string
import pyrolog
from pyromod import listen, ikb
from pyromod.types import ListenerTypes
from pyrogram import Client, filters, types
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import database

####

with open('config.toml', 'rb') as f:
    config = tomllib.load(f)

engine = create_engine(config['database_uri'])
database.Base.metadata.create_all(engine)

logger = pyrolog.get_colored_logger(log_level=config['log_level'])
logger.add_handler(pyrolog.FileHandler('log.txt', log_level='debug'))

####


def cbfilter(data):
    async def func(flt, _, query):
        return flt.data == query.data

    # "data" kwarg is accessed with "flt.data" above
    return filters.create(func, data=data)


def cbfilter_param(data):
    async def func(flt, _, query):
        if len(query.data) < len(flt.data):
            return False

        return query.data[:len(flt.data)] == flt.data

    # "data" kwarg is accessed with "flt.data" above
    return filters.create(func, data=data)


def q_error_handling(f):
    async def deco(client, q: types.CallbackQuery):
        try:
            await f(client, q)
        except Exception as e:
            logger.exception('in chat {} (@{}, {}) CQ with data "{}" caused exception: {}',
                             q.from_user.first_name, q.from_user.username, q.from_user.id, q.data, e)
    return deco


def cmd_error_handling(f):
    async def deco(client, m: types.Message):
        try:
            await f(client, m)
        except Exception as e:
            logger.exception('in chat {} (@{}, {}) command "{}" caused exception: {}',
                             m.from_user.first_name, m.from_user.username, m.from_user.id, m.text, e)
    return deco

RANDOM_ALPHABET = string.ascii_letters + string.digits + '-'


def random_string(length: int) -> str:
    return ''.join([random.choice(RANDOM_ALPHABET) for _ in range(length)])

####

kb_main_menu = ikb([
    [('🗒 Твои тесты', 'mytests'), ('➕ Новый тест', 'newtest')],
])

kb_newtest = ikb([
    [('➕ Новый вопрос', 'newquestion'), ('➖ Удалить вопрос', 'delquestion')],
    [('✅ Создать тест', 'submitnewtest'), ('❌ Отменить тест', 'cancelnewtest')],
])

currently_creating = {}

####

client = Client('bot', api_id=config['api_id'], api_hash=config['api_hash'], bot_token=config['bot_token'])


@client.on_message(filters.command('start'))
@cmd_error_handling
async def cmd_start(_, msg: types.Message):
    if len(msg.command) > 1:
        with Session(engine) as session:
            t = session.query(database.Test).where(database.Test.test_link == msg.command[1]).one_or_none()
            
            if t is None:
                    await msg.reply("""
☹️ Такого теста не существует... Но ты можешь создать свой!

🫂 Я Судья для друзей. Тут ты можешь легко создавать свои тесты на дружбу для того, чтобы узнать кто твой настоящий бро.

👉 Используй кнопки 😁
""".strip(), reply_markup=kb_main_menu)
                    return
            
            await msg.reply(f"""
📑 Тест `{t.name}`.

🫂 Я Судья для друзей. Тут ты можешь легко создавать свои тесты на дружбу для того, чтобы узнать кто твой настоящий бро.
""".strip(), reply_markup=ikb([
    [('👉 Начать тест', f'test:{t.test_link}')]
]))
            return

    await msg.reply("""
✋ Привет!

🫂 Я Судья для друзей. Тут ты можешь легко создавать свои тесты на дружбу для того, чтобы узнать кто твой настоящий бро.

👉 Используй кнопки 😁
""".strip(), reply_markup=kb_main_menu)


@client.on_callback_query(cbfilter('mytests'))
@q_error_handling
async def q_mytests(_, q: types.CallbackQuery):
    with Session(engine) as session:
        tests = session.query(database.Test).where(database.Test.creator_id == q.from_user.id).all()
        t_testers = {t.id:
            session.query(database.Tester).where(database.Tester.test_id == t.id).all()
            for t in tests
        }
        t_avg_correct = {t.id:
            ('Не доступно.'
              if len(t_testers[t.id]) == 0 else
              f'{(sum([tt.percents for tt in t_testers[t.id]]) / len(t_testers[t.id])):.2f}%'
            )
            for t in tests
        }
        
        if len(tests) == 0:
            await q.message.edit_text('☹️ У тебя нету своих тестов. Создай!', reply_markup=kb_main_menu)
            return

        bot_un = (await client.get_me()).username
    
        await q.message.edit_text('🗒 Твои тесты:\n\n' + '\n\n'.join([f'{i}. {t.name}\nСсылка: https://t.me/{bot_un}?start={t.test_link}\nПрошло: **{len(t_testers[t.id])}**\nПроцент правильных: **{t_avg_correct[t.id]}**' for i, t in enumerate(tests)]), reply_markup=kb_main_menu)


@client.on_callback_query(cbfilter('newtest'))
@q_error_handling
async def q_newtest(_, q: types.CallbackQuery):
    currently_creating[q.from_user.id] = {}
    test = currently_creating[q.from_user.id] if q.from_user.id in currently_creating else {}
    await q.message.edit_text("📝 **Создаём новый тест...**\n\n" + '\n'.join([f"{i+1}. {k} ({[v['*']]})" for i, (k, v) in enumerate(test.items())]),
                          reply_markup=kb_newtest)


@client.on_callback_query(cbfilter('newquestion'))
@q_error_handling
async def q_newquestion(_, q: types.CallbackQuery):
    if q.from_user.id not in currently_creating:
        await q.message.edit_text('☹️ Создание нового вопроса невозможно. Попробуй снова.', reply_markup=kb_main_menu)
        return

    msg = await client.ask(chat_id=q.from_user.id, text='❓ Напиши название вопроса.', filters=filters.text, timeout=3600)
    if msg is None:
        await q.message.edit_text('☹️ Создание нового вопроса отменено.\n\n' +  + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
        return
    question = msg.text
    
    await msg.delete()
    await msg.sent_message.delete()

    msg = await client.ask(chat_id=q.from_user.id, text=f'❓{question}\n\nНапиши варианты ответов. Каждый ответ с новой строки. Правильный ответ должен в конце иметь * (звёздочка будет скрыта после создания). Пример:\n\nарбуз\nбанан\nперсик\nщавель*\nПравильным вариантом будет щавель.', filters=filters.text, timeout=3600)
    if msg is None:
        await q.message.edit_text('☹️ Создание нового вопроса отменено.\n\n' + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
        return
    
    await msg.delete()
    await msg.sent_message.delete()

    variants = msg.text.splitlines()
    
    if len(variants) < 2:
        await q.message.edit_text('☹️ Создание нового вопроса отменено: ты указал меньше двух вариантов ответа.\n\n' + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
        return
    
    true_variant = None
    for i, v in enumerate(variants):
        if v[-1]=='*':
            if true_variant is not None:
                await q.message.edit_text('☹️ Создание нового вопроса отменено: ты указал звёздочку больше чем один раз.\n\n' + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
                return

            variants[i] = v[:-1]
            true_variant = v[:-1]

    if true_variant is None:
        await q.message.edit_text('☹️ Создание нового вопроса отменено: ты не указал правильный ответ звёздочкой.\n\n' + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
        return

    currently_creating[q.from_user.id][question] = {
        'variants': variants,
        '*': true_variant,
    }

    await q.message.edit_text('✅ Новый вопрос добавлен!\n\n' + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
    return


@client.on_callback_query(cbfilter('delquestion'))
@q_error_handling
async def q_delquestion(_, q: types.CallbackQuery):
    if q.from_user.id not in currently_creating:
        await q.message.edit_text('☹️ Удаление вопроса невозможно. Попробуй снова.', reply_markup=kb_main_menu)
        return
    
    msg = await client.ask(chat_id=q.from_user.id, text='Напиши цифру вопроса который ты хочешь удалить.\n\n'.join([f'{i+1}. {k}: {", ".join(v["variants"])}. Правильный: {v["*"]}\n' for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]) + '\n\nНапиши `!` чтобы отменить',
                           filters=filters.text, timeout=3600)
    
    if msg is None:
        await q.message.edit_text('👍 Удаление вопроса отменено.\n\n' + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
        return

    await msg.delete()
    await msg.sent_message.delete()
    
    if msg.text.strip() == '!':
        await q.message.edit_text('👍 Удаление вопроса отменено.\n\n' + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
        return

    try:
        idx = int(msg.text)
    except:
        await q.message.edit_text('👍 Удаление вопроса отменено: ты ввел не цифру!\n\n' + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
        return

    currently_creating[q.from_user.id].pop(list(currently_creating[q.from_user.id].keys())[idx-1])
    
    await q.message.edit_text(f'☹️ Вопрос #`{idx}` удален!\n\n' + '\n'.join([f"{i+1}. {k} ({v['*']})" for i, (k, v) in enumerate(currently_creating[q.from_user.id].items())]), reply_markup=kb_newtest)
    return


@client.on_callback_query(cbfilter('cancelnewtest'))
@q_error_handling
async def q_cancelnewtest(_, q: types.CallbackQuery):
    await q.message.edit_text('☹️ Создание нового теста отменено.', reply_markup=kb_main_menu)

    if q.from_user.id in currently_creating:
        currently_creating.pop(q.from_user.id)
        return


@client.on_callback_query(cbfilter('submitnewtest'))
@q_error_handling
async def q_cancelnewtest(_, q: types.CallbackQuery):
    logger.info('{} (@{}, {}) trying to submit a test.', q.from_user.first_name, q.from_user.username, q.from_user.id)

    if q.from_user.id not in currently_creating:
        await q.message.edit_text('☹️ Создание нового теста невозможно. Попробуй снова.', reply_markup=kb_main_menu)
        return
    
    if len(currently_creating) == 0:
        await q.message.edit_text('☹️ Создание нового теста отменено: Ты не добавил ни одного вопроса.', reply_markup=kb_newtest)
        return
    
    msg = await client.ask(chat_id=q.from_user.id, text='👉 Напиши название теста.', filters=filters.text, timeout=3600)
    if msg is None:
        await q.message.edit_text('☹️ Создание нового теста отменено. Попробуй снова создать тест.', reply_markup=kb_newtest)
        return
    
    await msg.delete()
    await msg.sent_message.delete()
    
    with Session(engine) as session:
        
        test_link = random_string(config['test_link_length'])
        
        test = database.Test(
            test_link=test_link,
            creator_id=q.from_user.id,
            name=msg.text,
            questions=[
                database.TestQuestion(
                    name=k,
                    variants=[
                    database.TestQuestionVariant(
                            value=vv,
                            correct=vv == v['*'],
                        ) for vv in v['variants']
                    ],
                ) for k, v in currently_creating[q.from_user.id].items()
            ],
        )
        
        session.add(test)
        session.commit()
        
    currently_creating.pop(q.from_user.id)
    
    bot_un = (await client.get_me()).username

    logger.info('{} (@{}, {}) created a new test "{}" link: {}', q.from_user.first_name, q.from_user.username, q.from_user.id, msg.text, f'https://t.me/{bot_un}?start={test_link}')
    
    await q.message.edit_text(f'✅ Новый тест создан!\n❗️ Его нельзя удалить. Он доступен только по ссылке.\n\nПерешли сообщение ниже друзьям!', reply_markup=kb_main_menu)
    await q.message.reply(f'👉👉👉 ПРОЙДИ ТЕСТ `{msg.text}` ОТ `{q.from_user.first_name}`!\n\n🔗 https://t.me/{bot_un}?start={test_link}')
    

@client.on_callback_query(cbfilter_param('test:'))
@q_error_handling
async def q_take_test(_, q: types.CallbackQuery):
    
    test_link = q.data[5:]
    
    with Session(engine) as session:
        t = session.query(database.Test).where(database.Test.test_link == test_link).one_or_none()
        
        if t is None:
                await q.message.reply("""
☹️ Такого теста не существует... Но ты можешь создать свой!

🫂 Я Судья для друзей. Тут ты можешь легко создавать свои тесты на дружбу для того, чтобы узнать кто твой настоящий бро.

👉 Используй кнопки 😁
""".strip(), reply_markup=kb_main_menu)
                return
        
        answers = []
        corrects = {}
        qs = t.questions
        qs_len = len(qs)

        for i, qq in enumerate(qs):
            rows_remain = len(qq.variants) % 2
            
            kb = ikb([
                [(qq.variants[i].value, str(qq.variants[i].id)), (qq.variants[i+1].value, str(qq.variants[i+1].id))] for i in range(0, len(qq.variants) - 1 if rows_remain else len(qq.variants), 2)
            ] + ([[(qq.variants[-1].value, str(qq.variants[-1].id))]] if rows_remain else []))

            await q.message.edit_text(
                f'👉 {t.name}\n❓{qq.name} ({i+1}/{qs_len})\n\n👇👇👇 Выбери правильный вариант.',
                reply_markup=kb
            )

            q_answer = await client.ask(chat_id=q.from_user.id, text=f'Жду...',listener_type=ListenerTypes.CALLBACK_QUERY, timeout=3600)
            
            await q_answer.sent_message.delete()
            
            if q_answer is None:
                await q.message.reply("""
☹️ Прохождение теста отменено.

🫂 Я Судья для друзей. Тут ты можешь легко создавать свои тесты на дружбу для того, чтобы узнать кто твой настоящий бро.

👉 Используй кнопки 😁
""".strip(), reply_markup=kb_main_menu)
                return
            
            answer = int(q_answer.data)
            
            for v in qq.variants:
                if v.correct:
                    corrects[qq] = v
                    if v.id == answer:
                        answers.append(1)
                        break
            else:
                answers.append(0)

        percents = (sum(answers) / qs_len) * 100

        tst = database.Tester(test_id=t.id, tester_id=q.from_user.id, percents=percents)
        session.add(tst)
        session.commit()

        await q.message.edit_text(
                f'🎉 Ты прошел тест `{t.name}` на **{percents:.2f}%**')
        
        logger.info('{} (@{}, {}) passed the test {} on {}%', q.from_user.first_name, q.from_user.username, q.from_user.id, t.name, percents)
    
    
        res = '\n'.join([
            ('✅' if answers[i] == 1 else '❌') + f' {qq.name} | Правильно: ' + f'{corr.value}' for i, (qq, corr) in enumerate(corrects.items())
        ])

        await q.message.reply(
                f'🎉 Результат.\n\n' + res,
                protect_content=True,
        )

        await client.send_message(t.creator_id, f'Результат `{q.from_user.first_name}`.\n\n' + res)

        await q.message.reply("""
Ты можешь легко создать свой тест!

🫂 Я Судья для друзей. Тут ты можешь легко создавать свои тесты на дружбу для того, чтобы узнать кто твой настоящий бро.

👉 Используй кнопки 😁
    """.strip(), reply_markup=kb_main_menu)

        await client.send_message(t.creator_id,
                f'❕ `{q.from_user.first_name} {q.from_user.last_name if q.from_user.last_name is not None else ""}` прошел тест `{t.name}` на **{percents:.2f}%**'.strip())

####

if __name__ == '__main__':
    client.run()
