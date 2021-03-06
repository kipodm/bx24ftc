Небольшой помощник, который из группы телеграм перекладывает аудиофайл в сделку Битрикс24

В идеале это должно выглядеть как на картинке ниже. Отправляем в группу аудиофайл разговора, в ответ бот присылает ссылку на сделку к которой он привязал этот файл.

# Содержание

[TOC]

------------

# Вступление

Для чего вообще это всё нужно было мне.
Нашему директору периодически звонят клиенты по поводу заказов. Задают всякие технические вопросы и т.п.
Директор записи таких звонков обычно отсылает в общую группу в Телеграм, чтобы все были в курсе таких звонков.
Хотелось автоматически привязывать эти звонки к соответствующей сделке.
Как вы понимаете не все звонки можно выкладывать, поэтому привязывать его телефон к битриксу нельзя.

Пришлось накостылять связку бота телеграм и Битрикс24 (у нас облако) через вебхуки.

# Установка

У нас этот сервис установлен на Ubuntu 18.04 На других системах не тестировалось, но т.к. всё написано
на питоне, то запускаться должен везде.

Но вот с установкой на других системах вам нужно будет разбираться самим.

В любом случае здесь попытаюсь установку описать для новичков.
Все команды выполнять от пользователя root

Устанавливает _git_ и _python3-venv_:

```shell script
apt install git python3-venv
```

Скачиваем проект (Здесь он помещён в папку /var/www/html/bx24ftc):
```shell script
cd /var/www/html/
git clone git@github.com:kipodm/bx24ftc.git
cd bx24ftc
```

Устанавливаем окружение.
```shell script
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp changed_bitrix24.py_new venv/lib/python3.6/site-packages/bitrix24/bitrix24.py
```

Последняя команда заменяет файл в библиотеке bitrix24. Это сделано потому, что в
оригинальной не работает команда crm.livefeedmessage.add. Исправил добавив кодировку utf-8

Далее нам нужно, чтобы скрипт запускался как сервис. Создадим такой сервис.
```shell script
nano /etc/systemd/system/bx24ftc.service
```

Вставляем сюда описание сервиса (не забудьте поменять пути, если у вас они отличаются).
```text
[Unit]
Description=audio adder bot service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/html/bx24ftc
Environment="PATH=/var/www/html/bx24ftc/"
ExecStart=/var/www/html/bx24ftc/venv/bin/python /var/www/html/bx24ftc/bx24ftc.py

[Install]
WantedBy=multi-user.target
```

Сохраняемся через Ctrl+X и затем Y

Регистрируем сервис и запускаем его:
```shell script
systemctl enable bx24ftc.service
```

# Конфиг скрипта
Далее нам нужно заполнить config.ini своими данными.
В принципе в config.ini есть пояснения для каждого параметра, но всё равно приведу их здесь

У нас звонки записываются и выкладываются приложением Automatic Call Recorder
Формат его файлов такой: call_13-51-52_IN_+79112212211.amr

Раздел общих настроек

>[basic]

В regex указывается правило для разделения имени файла на части для последующего вытаскивания из них номера телефона
Например для **`[^._]+`** файл с именем **`call_13-51-52_IN_+79112212211.amr`**
разделится на части: **call, 13-51-52, IN, +79112212211, amr**

>regex=[^._]+  

Допустимые расширения файлов. Допускаются буквы, цифры и знаки подчёркивания.
Если расширение файла не будет соответствовать одному из перечисленных, то бот его проигнорирует.

>accepted_extensions=amr, mp3, mp4

В number_position задеётся позиция номера телефона в имени файла.
Здесь вопреки традициям индекс первого элемента 1, а не 0
Для приведённого выше примера номер телефона будет на позиции 4
Если нужно считать с обратного конца, то ставим отрицательное число.
Таким образом с конца позиция номера телефона будет **-2**

>number_position=-2

Файл для логов

>logfile=audio_adder.log

Путь по которому сохраняются аудиофайлы.
Файлы сохраняются в формате timestamp-file_name
Т.е. для файла приведённого выше путь сохранения может быть такой:  
**`/var/www/html/audio.mydomain.com/1583871907-call_13-51-52_IN_+79112212211.amr`**

>save_path=/var/www/html/audio.mydomain.com/

Ссылка для добавления аудиофайла в комментарии.
Приведённый выше аудиофайл будет доступен по ссылке:
**`https://audio.mydomain.com/call_13-51-52_IN_+79112212211.amr`**

>audio_url=https://audio.mydomain.com/


Настройки для связи с Битрикс24

>[bitrix24]

Токен для вебхуков. Берётся в настройках своих приложений в Битрикс24.
Вот здесь справка: [Справка по веб-хукам](https://helpdesk.bitrix24.ru/open/5408147/)  
**Внимание! Никому не сообщайте ваш токен!!!**

>token=5k3ndk29ndowenrq

Ваш домен битрикса

>domain=mydomain.bitrix24.ru


Настройки бота телеграм.

>[telegram]

Токен бота, нужно взять в [@BotFather](https://t.me/BotFather)  
**Внимание! Никому не сообщайте токен вашего телеграм бота!**

>token=270485614:AAHfiqksKZ8WmR2zSjiQ7_v4TMAKdiHm9T0

ID чата, куда включён наш бот. Для получения ID можно подключить в чат бот [@RawDataBot](https://t.me/RawDataBot)

>chatid=-311111111

# Настройки NGINX
Для того, чтобы заработали ссылки нум нужно ещё настроить nginx. 

Кто предпочитает другой сервер, тот, наверное, может сам настроить решение под себя.

Ожидается, что домен audio.mydomain.com в DNS уже прописан

Устанавливаем **nginx** и **certbot**
```shell script
apt install nginx certbot
```

Создаём папку, куда будут складываться наши файлы:
```shell script
mkdir /var/www/html/audio.mydomain.com
```

Прописываем настройки сервера 

```shell script
nano /etc/nginx/conf.d/audio.mydomain.com.conf
```

Прописываем туда вот такую начальную конфигурацию:
```text
server {

}
```





