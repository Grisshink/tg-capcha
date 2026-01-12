import logging
import os
import numpy
import vnoise

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from random import randint, random, choice

from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from telegram.constants import ChatMemberStatus, ChatType, MessageEntityType, ParseMode
from dotenv import load_dotenv

font = ImageFont.truetype('./LiberationSerif-Italic.ttf', size=150)

load_dotenv()

unsolved_captchas = {}
rng = numpy.random.default_rng()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARN
)

letters = 'qwertyuipasdhjkzxcvbnm12345678'

captcha_usernames = ['grisshink', 'ygehr']
captcha_mentions = [f'@{user}' for user in captcha_usernames]

ping_photo_id = 'AgACAgIAAxkBAAICCWk_B_IT5OahJdFHlXDIE1kO3K5BAALJEmsbJX_5SVmTvyE2qDQLAQADAgADeQADNgQ'

def gen_text() -> str:
    return ''.join(choice(letters) for _ in range(6))

def new_captcha_image(text: str) -> bytes:
    bg_color = f'hsl({randint(0, 360)}, {randint(0, 100)}%, 80%)'
    fg_color = f'hsl({randint(0, 360)}, {randint(0, 100)}%, 20%)'
    if randint(1, 2) == 1:
        bg_color, fg_color = fg_color, bg_color

    img = Image.new("RGBA", (512, 256), bg_color)

    img_draw = ImageDraw.Draw(img)
    img_draw.text((256, 128), text, font=font, fill=fg_color, anchor='mm')
    img = img.rotate(randint(-25, 25), fillcolor=bg_color)

    np = numpy.asarray(img, copy=True)

    noise = vnoise.Noise(randint(0, 2**32))
    vert_samples = numpy.linspace(0.0, np.shape[0] / 32.0, np.shape[0])
    horiz_samples = numpy.linspace(0.0, np.shape[1] / 32.0, np.shape[1])
    noise_out = noise.noise2(vert_samples, horiz_samples)

    n = numpy.repeat(numpy.expand_dims(noise_out, axis=2), 3, axis=2)
    np[:,:,:3] += ((n > 0.3) & (n < 0.5)).astype(np.dtype) * 30 + (n * 30).astype(np.dtype)

    A = np.shape[0] / 8.0 * (random() * 0.5 + 0.5)
    w = (random() * 2.0 + 1.0) / np.shape[1]

    state = 0
    dist = randint(20, 100)
    shift = lambda x: A * numpy.sin(2.0*numpy.pi*x * w)
    for i in range(np.shape[1]):
        np[:,i] = numpy.roll(np[:,i], int(shift(i)), axis=0)
        if state == 1:
            np[:,i,:3] = numpy.invert(np[:,i,:3])

        dist -= 1
        if dist < 0:
            state = 1 if state == 0 else 0
            dist = randint(20, 100)

    img = Image.fromarray(np)
    img_io = BytesIO()
    img.save(img_io, format="PNG")

    return img_io.getvalue()

def gen_captcha(user_id: int) -> bytes:
    unsolved_captchas[user_id] = gen_text()
    return new_captcha_image(unsolved_captchas[user_id])

async def uncaptcha(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    if update.message is None: return

    chatMember = await update.effective_chat.get_member(update.effective_user.id)

    if (update.effective_chat.type != ChatType.PRIVATE and
        chatMember.status != ChatMemberStatus.ADMINISTRATOR and
        chatMember.status != ChatMemberStatus.OWNER):
        await update.message.reply_text('Ты не адмене, беги')
        return

    if update.message.reply_to_message is None or update.message.reply_to_message.from_user is None:
        await update.message.reply_text('Нужно ответить пользователю этой командой, чтобы разблокировать доступ')
        return

    reply_to = update.message.reply_to_message

    if reply_to.from_user.id not in unsolved_captchas:
        await update.message.reply_text('Пользователь уже прошёл капчу')
        return

    await reply_to.reply_markdown_v2(f'{reply_to.from_user.mention_markdown_v2()} ты был помилован великим адмене {update.message.from_user.mention_markdown_v2()}')
    del unsolved_captchas[reply_to.from_user.id]

async def captcha(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    if update.message is None: return

    reply_to = update.message

    chatMember = await update.effective_chat.get_member(update.effective_user.id)

    if (update.effective_chat.type == ChatType.PRIVATE or
        chatMember.status == ChatMemberStatus.ADMINISTRATOR or
        chatMember.status == ChatMemberStatus.OWNER) and \
        update.message.reply_to_message is not None and \
        update.message.reply_to_message.from_user is not None:
        reply_to = update.message.reply_to_message

    reply_member = await update.effective_chat.get_member(reply_to.from_user.id)
    if (reply_member.status == ChatMemberStatus.ADMINISTRATOR or
        reply_member.status == ChatMemberStatus.OWNER) and reply_to.from_user.id not in unsolved_captchas:
        await update.message.reply_text('По своим не стреляем ;)')
        return

    await reply_to.reply_photo(
        gen_captcha(reply_to.from_user.id), 
        caption=f'Не будь винляторным, {reply_to.from_user.mention_markdown_v2()}, подтверди капчу как настоящий мусороид:',
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def send_captcha(message):
    await message.reply_photo(
        gen_captcha(message.from_user.id), 
        caption=f'Не будь винляторным, {message.from_user.mention_markdown_v2()}, подтверди капчу как настоящий мусороид:',
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    if message.from_user.id == 6074263390:
        await message.reply_photo(ping_photo_id)
        await message.delete()


async def user_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None: return
    if update.message.from_user is None: return

    user_id = update.message.from_user.id
    if user_id not in unsolved_captchas:
        for entity in update.message.entities:
            if entity.type == MessageEntityType.MENTION:
                if update.message.parse_entity(entity).lower() in captcha_mentions:
                    await send_captcha(update.message)
                    return
            elif entity.type == MessageEntityType.TEXT_MENTION:
                if entity.user.username.lower() in captcha_usernames:
                    await send_captcha(update.message)
                    return
        for entity in update.message.caption_entities:
            if entity.type == MessageEntityType.MENTION:
                if update.message.parse_caption_entity(entity).lower() in captcha_mentions:
                    await send_captcha(update.message)
                    return
            elif entity.type == MessageEntityType.TEXT_MENTION:
                if entity.user.username.lower() in captcha_usernames:
                    await send_captcha(update.message)
                    return
        return

    if update.message.text is None:
        await update.message.reply_text('ГДЕ КАПЧА?!1!11!')
    elif update.message.text.lower() != unsolved_captchas[user_id]:
        await update.message.reply_text('НЕПРАВИЛЬНА!1!11!')
    else:
        await update.message.reply_text('Всё верно, хорошего дня ;)')
        del unsolved_captchas[user_id]

    try:
        await update.message.delete()
    except:
        await update.message.reply_text("ААА, Я НЕ АДМИН")

async def user_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None: return
    if update.message.from_user is None: return

    user_id = update.message.from_user.id
    if user_id not in unsolved_captchas: return

    await update.message.reply_text('ГДЕ КАПЧА?!1!11!')

    try:
        await update.message.delete()
    except:
        await update.message.reply_text("ААА, Я НЕ АДМИН")

async def new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None: return
    print('new member', update.message.new_chat_members[0].id)
    await update.message.reply_photo(
        gen_captcha(update.message.new_chat_members[0].id), 
        caption=f'Не будь винляторным, {update.message.new_chat_members[0].mention_markdown_v2()}, подтверди капчу как настоящий мусороид:',
        parse_mode=ParseMode.MARKDOWN_V2,
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None: return
    await update.message.reply_text('/captcha - Казнить.\n/uncaptcha - Помиловать.')

if __name__ == '__main__':
    application = ApplicationBuilder().token(os.getenv('BOT_TOKEN', '')).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('captcha', captcha))
    application.add_handler(CommandHandler('uncaptcha', uncaptcha))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member))
    application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & filters.USER, user_confirm))
    application.add_handler(MessageHandler(filters.USER, user_msg))
    
    application.run_polling()
