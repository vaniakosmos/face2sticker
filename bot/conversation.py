import logging
import re
from io import BytesIO

from telegram import Bot, Update
from telegram.error import BadRequest
from telegram.ext import CommandHandler, ConversationHandler, Filters, MessageHandler

import logs
import stickerizer
from config import DEBUG
from .decorators import log


logs.set_up(DEBUG)
logger = logging.getLogger(__name__)

TITLE, NAME, PHOTO = range(3)


@log
def create_command(bot: Bot, update: Update):
    update.message.reply_text(
        'How pack should be titled?\n'
        '\n'
        'Title must be 1-64 characters long.'
    )
    return TITLE


@log
def title_handler(bot: Bot, update: Update, user_data: dict):
    title = update.message.text
    if len(title) > 64:
        logger.debug(f'title ({len(title)}::{title}) is too long')
        msg = 'Title must be 1-64 characters long.'
        update.message.reply_text(msg)
        return TITLE

    user_data['title'] = title

    name_len = 64 - len('_by_' + bot.username)
    update.message.reply_text(
        f'Nice one. Now provide name for the pack.\n'
        f'\n'
        f'It must be short (1-{name_len} chars), '
        f'unique for this bot single word (not spaces, latin letters and digits).\n'
        f'It will be used in pack url.'
    )
    return NAME


@log
def name_handler(bot: Bot, update: Update, user_data: dict):
    name = update.message.text + '_by_' + bot.username

    long_name = len(name) > 64
    bad_typing = not re.match(r'^[a-zA-Z0-9_]+$', name)
    not_unique = False  # todo

    try:
        bot.get_sticker_set(name)
        not_unique = True
    except BadRequest as e:
        logger.debug(str(e))

    if long_name or bad_typing or not_unique:
        update.message.reply_text(
            'Name can contain only english letters, digits and underscores '
            'Must begin with a letter, can\'t contain consecutive underscores.\n'
            '1-64 characters')
        return NAME

    user_data['name'] = name
    user_data['photos'] = []

    update.message.reply_text(
        f'Good. Now you can send me selfies.\n'
        f'\n'
        f'Type /finish when you are done.'
    )
    return PHOTO


@log
def photo_handler(bot: Bot, update: Update, user_data: dict):
    photo_sizes = update.message.photo

    # todo: limit number of photos
    # todo: accept documents
    if photo_sizes is None:
        update.message.reply_text('Waiting for photo...')
        return PHOTO

    photo = photo_sizes[-1]  # photo with max size
    user_data['photos'].append(photo.file_id)

    # delete previous notification
    msg = user_data.get('received', None)
    if msg:
        msg.delete()

    photo_num = len(user_data['photos'])
    msg = update.message.reply_text(f'Received {photo_num} photo(s).\n'
                                    f'Type /finish if you are done.')
    user_data['received'] = msg
    return PHOTO


@log
def stickerize_photos(bot: Bot, update: Update, photos: list):
    for i, photo in enumerate(photos):
        logger.debug(f'Processing photo {i+1}/{len(photos)}...')
        file = bot.get_file(photo)
        out = BytesIO()
        file.download(out=out)
        for image, emojis in stickerizer.make_stickers(out):
            file = bot.upload_sticker_file(user_id=update.message.from_user.id,
                                           png_sticker=image)
            yield file.file_id, emojis
        out.close()
    logger.debug(f'Finished stickerization.')


@log
def finish_command(bot: Bot, update: Update, user_data: dict):
    title, name, photos = user_data['title'], user_data['name'], user_data['photos']

    if not photos:
        update.message.reply_text('No selfies - no stickers 😜')
        return PHOTO

    first = True
    for file_id, emojis in stickerize_photos(bot, update, photos):
        if first:
            first = False
            bot.create_new_sticker_set(user_id=update.message.from_user.id,
                                       name=name, title=title,
                                       png_sticker=file_id, emojis=emojis)
        else:
            bot.add_sticker_to_set(user_id=update.message.from_user.id,
                                   name=name,
                                   png_sticker=file_id, emojis=emojis)

    sticker_set = bot.get_sticker_set(name)

    update.message.reply_text('Here you go!')
    update.message.reply_sticker(sticker_set.stickers[0])
    return ConversationHandler.END


@log
def cancel_command(bot: Bot, update: Update, user_data: dict):
    user_data.clear()
    update.message.reply_text('Pack creation was canceled.')
    return ConversationHandler.END


conversation_handler = ConversationHandler(
    entry_points=[CommandHandler('create', create_command)],

    states={
        TITLE: [MessageHandler(Filters.text, title_handler, pass_user_data=True)],

        NAME: [MessageHandler(Filters.text, name_handler, pass_user_data=True)],

        PHOTO: [MessageHandler(Filters.photo, photo_handler, pass_user_data=True),
                CommandHandler('finish', finish_command, pass_user_data=True)],
    },

    fallbacks=[CommandHandler('cancel', cancel_command, pass_user_data=True)]
)
