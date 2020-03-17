# -*- coding: utf-8 -*-

__author__ = "Igor E. Kogan"
__copyright__ = "Copyright 2020, Rimamid"
__credits__ = ["Igor E. Kogan"]
__license__ = "GPLv3"
__version__ = "0.1"
__maintainer__ = "Igor E. Kogan"
__status__ = "Develop"

import configparser
import telegram
from telegram.ext import Updater, MessageHandler, Filters
import logging
import re
import time
from bitrix24 import *

CONFIG_FILE = 'config.ini'

bot_token = ''
chat_id = ''
bitrix24_token = ''
bitrix24_domain = ''
logfile = ''
telno_split_regex = ''
save_path = ''
audio_url = ''
number_position = 0
accepted_extensions = []


# Все пояснения значений можно найти в описаниях конфигурационного файла config.ini
try:
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    bot_token = config['telegram']['token']
    chat_id = config['telegram']['chatid']

    bitrix24_token = config['bitrix24']['token']
    bitrix24_domain = str(config['bitrix24']['domain']).rstrip('/').split('//')[-1]

    logfile = config['basic']['logfile']
    telno_split_regex = config['basic']['regex']
    save_path = str(config['basic']['save_path']).rstrip('/') + '/'
    audio_url = str(config['basic']['audio_url']).rstrip('/') + '/'
    number_position = int(config['basic']['number_position'])
    if number_position > 0:
        number_position -= 1
    elif number_position == 0:
        raise configparser.ParsingError(
            '\nЗначение индекса номера телефона в файле (number_position) '
            'должно быть отличным от нуля!\n')

    split_re = re.compile(r'\w+')
    accepted_extensions = [v for v in split_re.findall(
        config['basic']['accepted_extensions'])]
except configparser.Error as pe:
    print('\n\nОшибка чтения конфигурационного файла!\n'
          'Или неверно задана конфигурация или ошибка возникла при присвоении значений!\n'
          'Здесь объяснений нет, попробуйте посмотреть в логе ошибки ниже.\n\n')
    print(pe, '\n')
    exit(1)
except Exception as e:
    print('\nНепредвиденная ошибка в обработке конфигурационного файла!\n\n')
    print(e, '\n')
    exit(1)

logging.basicConfig(filename=logfile, level=logging.ERROR)

# Конфигурируем подключение к нашему Битрикс24
bx24 = Bitrix24('https://%s/rest/1/%s' % (bitrix24_domain, bitrix24_token))

# Конфигурируем подклюючение к Telegram боту
updater = Updater(token=bot_token, use_context=True)
dispatcher = updater.dispatcher

# Регулярка для разделения имени файла на части из которых потом вытащим номер телефона и расширение
telno = re.compile(telno_split_regex)

# URL для приписывания в сообщении бота для быстрой навигации менеджеров
COMPANY_URL = 'https://' + bitrix24_domain + '/crm/company/details/%s/'
CONTACT_URL = 'https://' + bitrix24_domain + '/crm/contact/details/%s/'
LEAD_URL = 'https://' + bitrix24_domain + '/crm/lead/details/%s/'
DEAL_URL = 'https://' + bitrix24_domain + '/crm/deal/details/%s/'


def add_audio_to_deal(deal_id, url):
    """
    Метод создаёт комментарий в лента событий сделки и вставляет туда ссылку на аудиофайл
    :param deal_id:  идентификатор сделки
    :param url: ссылка на аудиофайл
    :return: True, если комментарий создан удачно, False в ином случае
    """

    # Здесь BB кодами задаётся заголовок сообщения. Сейчас шрифт больше обычного и его цвет синий
    message = '[COLOR=#2f3192][SIZE=14pt]Автоматически прикреплённое аудио[/SIZE][/COLOR]\n'
    message += '%s' % str(url)

    # "ENTITYTYPEID": 2 означает, что искать по ID нужно среди сделок
    live_data = {"POST_TITLE": "Автоматически прикреплённое аудио",
                 "MESSAGE": message,
                 "ENTITYTYPEID": 2,
                 "ENTITYID": int(deal_id)
                 }

    try:
        bx24.callMethod('crm.livefeedmessage.add', fields=live_data)
    except BitrixError as be:
        logging.error(str(be))
        return False
    return True


def get_stages():
    """
    Получаем из Битрикс24 статусы сделок с описаниями и ID

    :return: словарь списков статусов сделок или пустой словарь, если возникла ошибка
    process_stages: Список статусов группы в процессе (все у которых прописано process),
    process_stages_ids: Список ID статусов в группе в процессе (все у которых прописано process),
    finished_stages: Список статусов в группе завершённые (все у которых прописано не process),
    finished_stages_ids: Список ID статусов в группе завершённые (все у которых прописано не process)
    """
    # TO_DO: заменить списки на сеты, раз они не меняются
    process_stages = []
    finished_stages = []
    process_stages_ids = []
    finished_stages_ids = []
    try:
        # Здесь как раз получаем весь список доступных статусов у сделок
        stages_types = bx24.callMethod('crm.status.list', filter={
                                       "ENTITY_ID": "DEAL_STAGE"})
    except BitrixError as be:
        logging.error(be)
        return {}

    for stage in stages_types:
        semantics = str(stage['EXTRA']['SEMANTICS']).lower()
        if semantics == 'process':
            process_stages.append({'STATUS_ID': str(stage['STATUS_ID']), 'NAME': str(
                stage['NAME']), 'SEMANTICS': str(stage['EXTRA']['SEMANTICS']).lower()})
            process_stages_ids.append(str(stage['STATUS_ID']))
        else:
            finished_stages.append({'STATUS_ID': str(stage['STATUS_ID']),
                                    'NAME': str(stage['NAME']),
                                    'SEMANTICS': str(stage['EXTRA']['SEMANTICS']).lower()})
            finished_stages_ids.append(str(stage['STATUS_ID']))
    return {'process_stages': process_stages,
            'process_stages_ids': process_stages_ids,
            'finished_stages': finished_stages,
            'finished_stages_ids': finished_stages_ids}


def create_contacts_list(contacts, number):
    """
    Собираем часть сообщения касаемую списка лидов, контактов и сделок с похожим номером телефона
    :param contacts: Полученный из Битрикс24 словарь лидов, контактов и компаний с найденным номером телефона.
                    Словарь имеет вид: {'LEAD': {1,2,3}, 'CONTACT': {4,5,6}, 'COMPANY': {7,8,9}},
                    где цифры - это ID контактов этого типа.
    :param number: Номер телефона, нужен для вставки в сообщение
    :return: Форматированный тест сообщения со списком контактов
    """

    # Для формирования правильных ссылок нужно указывать для каждого типа контакта свой URL
    names = [['LEAD', 'Лидов', LEAD_URL],
             ['CONTACT', 'Контактов', CONTACT_URL],
             ['COMPANY', 'Компаний', COMPANY_URL]]

    bot_message = 'Найдены следующие контакты с номером похожим на <b>%s</b>:\n\n' % number

    for item in names:
        if item[0] in contacts:
            bot_message += '<b>%s</b>: %s\n' % (
                item[1], len(contacts[item[0]]))
            i = 1
            for contact_id in contacts[item[0]]:
                url = item[2] % contact_id
                bot_message += '%s. <a href="%s">%s</a>\n' % (i, url, url)
                i += 1
    return bot_message + '\n'


def search_deals_with_number(number, process_stage_ids):
    """
    Поиск сделок в которых учавствуют контакты с похожими номерами телефонов
    Для поиска контактов с похожими номерами полностью полагаемся на Битрикс24 и его метод crm.duplicate.findbycomm
    :param number: заданный номер телефона в любом формате
    :param process_stage_ids: ID стадий сделок, которые ещё не завершены
    :return: список сделок в процессе, список завершённых сделок, форматированное сообщение для бота
    """

    # Поиск контактов с заданным номером среди лидов, контактов и сделок
    try:
        contacts_with_number = bx24.callMethod('crm.duplicate.findbycomm',
                                               type="PHONE",
                                               values=[number])
    except BitrixError as be:
        logging.error(be)
        return {}, {}, 'Непредвиденная ошибка при попытке поиска номера телефона <b>%s</b> ' \
                       'на сервере Битрикс24.\n' % number
    if len(contacts_with_number) == 0:
        return {}, {}, 'Не найдено ни одного контакта с номером телефона похожим на <b>%s</b>, ' \
                       'пожалуйста внесите номер телефона в контакты и перезагрузите файл.\n' % number
    else:
        # Если есть хотя бы один контакт, то формируем сообщение для бота со списком
        bot_message = create_contacts_list(contacts_with_number, number)

    # Поиск актуальных сделок
    process_deals_dict = {}
    finished_deals_dict = {}
    for key, value in contacts_with_number.items():
        try:
            # Получаем список сделок для каждого найденного типа контакта - отдельно по лидам, контакта и компаниям
            deals = bx24.callMethod('crm.deal.list',
                                    order={"ID": "ASC"},
                                    filter={"%s_ID" % key: value},
                                    select=["ID", "STAGE_ID"])
            # Проверяем все сделки на тип стадии - в процессе или завершена
            for deal in deals:
                if deal['STAGE_ID'] in process_stage_ids:
                    process_deals_dict[deal['ID']] = deal['STAGE_ID']
                else:
                    finished_deals_dict[deal['ID']] = deal['STAGE_ID']
        except BitrixError as be:
            logging.error(be)
            return {}, {}, 'Непредвиденная ошибка при попытке получения списка сделок контакта.\n'
    return process_deals_dict, finished_deals_dict, bot_message


def call_catcher(update, context):
    """
    Хэндлер Telegram бота, который мониторит сообщения в группе
    :param update: Параметр бота
    :param context: параметр бота
    :return: ничего не возвращаем
    """

    # Проверяем в правильном ли чате нам отправили сообщение
    if str(update.effective_chat.id) != chat_id:
        return

    # разделяем имя файла на части и если смотрит соответствует ли расширение заданным
    file_name = str(update.message.document.file_name).lower().replace('+', '_')
    file_split = telno.findall(file_name)
    if file_split[-1] not in accepted_extensions:
        return

    # Вот здесь как раз вытаскиваем номер телефона из имени файла по позиции заданной в конфиге
    call_number = file_split[number_position]

    process_deals, finished_deals, bot_message = search_deals_with_number(call_number, stages['process_stages_ids'])
    number_in_process = len(process_deals)
    number_finished = len(finished_deals)

    do_download = True
    add_to_deal = True
    deal_id = ''

    """
    Логика такая:
    Если не найдено ни одной сделки в процессе, то файл не скачиваем
    Если найдена одна сделка в процессе, то файл скачиваем, формируем ссылку на него и прикрепляем к комменту
    Если сделок в процессе больше одной, то скачиваем, формируем ссылку, но просим пользователя прикрепить 
    к комментарию самостоятельно
    """
    if not number_in_process:
        bot_message = '\n<b>Внимание! Аудиофайл не привязан к сделкам!</b>\n\n' + bot_message
        bot_message += '\nНе найдено активных сделок!\n'
        do_download = False
    elif number_in_process > 1:
        add_to_deal = False
        bot_message = '\n<b>Внимание! Аудиофайл не привязан к сделкам!</b>\n\n' + bot_message
        bot_message += 'Найдено больше одной активной сделки. ' \
                       'Я не могу принять такого важного решения. ' \
                       'Пожалуйста прикрепите ссылку на файл вручную.\n' \
                       '<b>Список активных сделок:</b>\n'
        i = 1
        for deal_id in process_deals:
            url = DEAL_URL % deal_id
            bot_message += '%s. <a href="%s">%s</a> ' \
                           '— <b>%s</b>\n' % (i, url, url,
                                              stages_dict[process_deals[deal_id]])
            i += 1
    else:
        deal_id, deal_stage = process_deals.popitem()
        url = DEAL_URL % deal_id
        header = '\n<b>Аудиофайл привязан к сделке %s</b>\n\n' % deal_id
        bot_message = header + bot_message
        bot_message += 'Найдена одна активная сделка со статусом <b>%s</b>, ' \
                       'привязываемся к ней:\n' % stages_dict[deal_stage]
        bot_message += '<a href="%s">%s</a>\n' % (url, url)

    # Здесь как раз происходит скачивание файла и формирование ссылки на него
    if do_download:
        file = context.bot.getFile(update.message.document.file_id)
        timestamp = int(time.time())
        audio_file_name = '%s-%s' % (timestamp, file_name)
        file_path = '%s%s' % (save_path, audio_file_name)
        file.download(custom_path=file_path)
        file_url = '%s%s' % (audio_url, audio_file_name)
        if not add_to_deal:
            bot_message += '\nСсылка для прослушивания:\n' \
                           '<a href="%s">%s</a>\n' \
                           'Добавьте эту ссылку в соответствующую сделку.\n' % (
                               file_url, file_url)
        else:
            if not add_audio_to_deal(deal_id, file_url):
                bot_message += '\nНе удалось прикрепить аудиофайл к сделке: <b>Ошибка обращения к Битрикс24</b>\n' \
                               'Вы можете попробовать прикрепить ссылку на аудиофайл вручную:\n' \
                               '<a href="%s">%s</a>\n' % (file_url, file_url)

    bot_message += '\nЗавершённых сделок связанных с этим номером телефона: <b>%s</b>' % number_finished
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=bot_message,
        parse_mode=telegram.ParseMode.HTML,
        reply_to_message_id=update.message.message_id)
    return


# Перед запуском формируем списки типов стадий и их идентификаторы.
# При изменении списков в Битрикс24 скрипт нужно перезапускать
stages = get_stages()
if not stages:
    logging.error('Не удалось получить стадии сделок от Битрикс24')
    exit(1)
stages_dict = {}
for stage_status in stages['process_stages']:
    stages_dict[stage_status['STATUS_ID']] = stage_status['NAME']

messege_handler = MessageHandler(Filters.document, call_catcher)
dispatcher.add_handler(messege_handler)

updater.start_polling()
