import requests
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import os
from urllib.parse import urlparse
from moviepy.editor import VideoFileClip, concatenate_videoclips
from langchain_openai import ChatOpenAI
from langchain.schema import SystemMessage, HumanMessage
from runwayml import RunwayML, APIError
import time
import base64
import glob


# Функция для кодирования изображения в Data URI
def encode_image_to_data_uri(filename):
    response = requests.get(filename)
    encoded_image = base64.b64encode(response.content).decode('utf-8')
    #with open(filename, "rb") as image_file:
    #encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
    # Определение MIME-типа на основе расширения файла
    file_extension = filename.split('.')[-1].lower()
    if file_extension in ['jpg', 'jpeg']:
        mime_type = 'jpeg'
    elif file_extension == 'png':
        mime_type = 'png'
    elif file_extension == 'webp':
        mime_type = 'webp'
    else:
        raise ValueError("Unsupported file type. Please upload a JPEG, PNG, or WebP image.")
    # Создание Data URI
    return f"data:image/{mime_type};base64,{encoded_image}"

# Функция для проверки статуса задачи
def check_task_status(client, task_id):
    while True:
        task = client.tasks.retrieve(task_id)
        print(f"Текущий статус задачи {task_id}: {task.status}")
        if task.status == "SUCCEEDED":
            print(f"Задача {task_id} успешно завершена!")
            return task
        elif task.status == "FAILED":
            print(f"Задача {task_id} завершилась с ошибкой.")
            return task
        else:
            # Ждем 10 секунд перед следующей проверкой
            time.sleep(10)

# Функция для генерации промптов
def generate_prompts(biography, num_prompts):
    try:
        main_prompt = (
            f"Based on the following biography:\n\n{biography}\n\n"
            f"Generate {num_prompts} unique prompts for animating photos. "
            f"At the end of each prompt, add a description of the lighting based on the mood of the biography, for example: 'Soft and warm lighting with highlights appearing, etc.' "
            f"All prompts should be in English. "
            f"Do not use people's names; use terms like person/man/woman, etc. "
            f"Present them as a list, each prompt on a separate line without numbering or additional explanations."
        )
        messages = [
            SystemMessage(content="You are an assistant that generates creative prompts for animating photos."),
            HumanMessage(content=main_prompt)
        ]
        res = chatgpt.invoke(messages)
        cleaned_message = res.content.strip()
        prompts = [prompt.strip() for prompt in cleaned_message.split('\n') if prompt.strip()]
        if len(prompts) < num_prompts:
            print("Предупреждение: Сгенерировано меньше промптов, чем ожидалось.")
        return prompts[:num_prompts]
    except OpenAIError as e:
        raise RuntimeError(f"OpenAI API error: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {e}")


token = 'tg_token'
rw_key = 'key_'
openai_key = 'sk-'
# Токен вашего бота
bot = telebot.TeleBot(token)

# Инициализация ChatGPT с моделью 'gpt-4'
chatgpt = ChatOpenAI(api_key=openai_key, model='gpt-4o-2024-11-20')
# Инициализация клиента
client = RunwayML(api_key=rw_key)

# Хранилище данных пользователя
user_data = {}


def get_memory_page_from_url(page_url, tok):
    """
    Функция для получения информации о странице памяти по URL.

    :param page_url: URL страницы памяти
    :param token: Токен авторизации
    :return: Ответ от API в формате JSON (если успешен), иначе None
    """
    try:
        # Извлекаем page_id из URL
        parsed_url = urlparse(page_url)
        page_id = parsed_url.path.split('/')[-1]

        if not page_id.isdigit():
            raise ValueError(f"Некорректный ID страницы в URL: {page_url}")

        # Формируем URL для API
        api_url = f"https://mc.dev.rand.agency/api/page/{page_id}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json;charset=UTF-8",
            "Authorization": f"Bearer {tok}"
        }

        # Делаем запрос к API
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()  # Выбрасывает исключение для кодов 4xx/5xx
        return response.json()  # Возвращаем JSON-ответ

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при выполнении запроса: {e}")
        return None
    except ValueError as ve:
        print(f"Ошибка: {ve}")
        return None


def process_memory_page(data):
    """
    Обрабатывает данные страницы памяти и возвращает биографию, список фотографий и главное фото.
    """
    try:
        # Извлекаем данные
        biography = data.get("biographies", [])
        photos = [photo.get("url") for photo in data.get("photos", [])]
        main_image = data.get("main_image", None)

        # Возвращаем результат
        return {
            "biography": biography,
            "photos": photos,
            "main_image": main_image
        }
    except Exception as e:
        return {"error": str(e)}


def get_access_token(email: str, password: str, device: str) -> str:
    url = "https://mc.dev.rand.agency/api/v1/get-access-token"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json;charset=UTF-8"
    }
    payload = {
        "email": email,
        "password": password,
        "device": device
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Проверяем, был ли запрос успешным
        data = response.json()
        return data.get("access_token", "")
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе токена: {e}")
        return None

def combine_biography_text(biographies):
    """
    Объединяет все заголовки и тексты разделов биографии в одну строку.
    """
    if not biographies:
        return "Биография отсутствует."

    # Сортируем разделы по порядковому номеру
    sorted_biographies = sorted(biographies, key=lambda x: x.get("order", 0))

    # Формируем текст
    combined_text = ""
    for section in sorted_biographies:
        title = section.get("title", "Без названия")
        description = section.get("description", "")

        # Добавляем заголовок и текст раздела
        combined_text += f"{title}\n{description}\n\n"

    return combined_text.strip()


# Команда /start
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_data[chat_id] = {}  # Инициализируем хранилище для пользователя
    bot.send_message(
        chat_id,
        "Я бот проекта «Код Памяти», помогу вам по шагам собрать и заполнить биографию вашего родственника.",
        reply_markup=generate_start_buttons()
    )


def get_individual_pages(tok):
    """
    Делает запрос к API для получения страниц памяти.

    Args:
        token (str): Токен аутентификации пользователя.

    Returns:
        list: Список страниц памяти, если запрос успешен.
        str: Сообщение об ошибке, если запрос не успешен.
    """
    url = "https://mc.dev.rand.agency/api/cabinet/individual-pages"
    headers = {
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers)
        return response

    except requests.exceptions.RequestException as e:
        print(f"Ошибка: Не удалось подключиться к серверу. {str(e)}")
        return None

# Генерация кнопки "Давай начнём!"
def generate_start_buttons():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("Давай начнём!"))
    return markup


def generate_ok():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("Хорошо!"))
    return markup


# Запрашиваем email
def ask_email(chat_id):
    bot.send_message(chat_id, "Напишите свой Email:")

def prompt_for_photos(chat_id):
    """
    Запрос загрузки фотографий у пользователя.
    """
    bot.send_message(
        chat_id,
        "Пожалуйста, загрузите фотографии для страницы памяти. Вы можете загрузить их по одной."
    )

def prompt_for_biography(chat_id):
    """
    Запрос загрузки биографии у пользователя.
    """
    bot.send_message(
        chat_id,
        "Пожалуйста, напишите текст биографии для страницы памяти."
    )
def add_to_video_queue(data, chat_id):
    """
    Добавление страницы памяти в очередь для генерации видео.
    """
    # Здесь добавляется логика генерации видео
    bot.send_message(
        chat_id,
        "Страница добавлена в очередь на генерацию видео. Мы сообщим вам, когда видео будет готово."
    )

    num_prompts = len(data['photos'])
    prompts = generate_prompts(data['biography'], num_prompts)
    print(f"Сгенерированные промпты: \n\n{prompts}")
    # Список для хранения путей к сгенерированным видео
    generated_videos = []

    # Обработка каждой фотографии
    for idx, photo in enumerate(data['photos']):
        print(f"\nОбработка фотографии {idx+1}/{len(data['photos'])}: {photo}")
        # Кодирование изображения
        data_uri = encode_image_to_data_uri(photo)
        # Получение соответствующего промпта
        prompt = prompts[idx] if idx < len(prompts) else "Animate this photo."
        # Создание задачи
        try:
            task = client.image_to_video.create(
                model='gen3a_turbo',
                prompt_image=data_uri,
                prompt_text=prompt,
                duration=5,  # Продолжительность видео в секундах (5 или 10)
                ratio="1280:768",  # Соотношение сторон видео
                watermark=False  # Добавить ли водяной знак
            )
            task_id = task.id
            print(f"Задача создана с ID: {task_id}")
        except APIError as e:
            print(f"Ошибка при создании задачи для фотографии {photo}: {e}")
            continue  # Переходим к следующей фотографии

        # Проверка статуса задачи
        completed_task = check_task_status(client, task_id)

        # Загрузка полученного видео
        if completed_task.status == "SUCCEEDED":
            output_url = completed_task.output[0]
            print(f"Ссылка на видео: {output_url}")

            # Скачивание видео с использованием wget
            video_filename = f"output_{idx+1}.mp4"
            os.system(f'wget "{output_url}" -O {video_filename}')
            print(f"Видео загружено как {video_filename}")
            generated_videos.append(video_filename)
        else:
            print(f"Не удалось сгенерировать видео для фотографии {photo}.")

    # Проверка наличия сгенерированных видео
    if not generated_videos:
        raise RuntimeError("Нет сгенерированных видео для объединения.")

    print("\nОбъединение всех сгенерированных видео в одно финальное видео...")

    # Загрузка всех видеофайлов
    clips = []
    for video in generated_videos:
        if os.path.exists(video):
            clip = VideoFileClip(video)
            clips.append(clip)
        else:
            print(f"Видеофайл {video} не найден и будет пропущен.")

    if not clips:
        raise RuntimeError("Нет доступных видеоклипов для объединения.")

    # Объединение видео
    final_clip = concatenate_videoclips(clips, method="compose")

    # Сохранение финального видео
    final_video_filename = "final_output.mp4"
    final_clip.write_videofile(final_video_filename, codec="libx264", audio_codec="aac")

    print(f"Финальное видео сохранено как {final_video_filename}")
    with open(final_video_filename, 'rb') as video_file:
        bot.send_video(
            chat_id,
            video_file,
            caption="🎥 Вот ваше сгенерированное видео на основе страницы памяти!",
            supports_streaming=True  # Позволяет пользователю начать просмотр до полной загрузки
        )


# Обрабатываем текстовые сообщения
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text

    if chat_id not in user_data:
        bot.send_message(chat_id, "Нажмите /start, чтобы начать.")
        return
    if text == "Давай начнём!":
        bot.send_message(
            chat_id,
            "Для того, чтобы начать заполнять страницы памяти, вам необходимо войти в личный кабинет через этого бота.\n\n"
            "Если не помните пароль, перейдите на сайт и сбросьте его себе на указанный при регистрации Email."
        )
        ask_email(chat_id)
    elif "email" not in user_data[chat_id]:
        # Сохраняем email
        user_data[chat_id]["email"] = text
        bot.send_message(chat_id, "Напишите свой пароль:")
    elif "password" not in user_data[chat_id]:
        # Сохраняем пароль
        user_data[chat_id]["password"] = text
        confirm_credentials(chat_id)
    elif message.text == 'Продолжить':
        bot.send_message(chat_id, "Отправляю запрос...")
        # Здесь выполняем запрос к API для аутентификации
        tok = get_access_token(
            user_data[chat_id]["email"],
            user_data[chat_id]["password"],
            "bot-v0.0.1"
        )
        if tok:
            # Пример успешного результата:
            bot.send_message(chat_id, "✅ Аутентификация пройдена\nТы оказался в главном меню 😊")
            user_data[chat_id]["token"] = tok
            show_main_menu(chat_id)
        else:
            bot.send_message(chat_id, "❌ В процессе аутентификации возникла ошибка. Проверьте введенные данные",
                             reply_markup=generate_ok())

    elif text == "Хорошо!":
        try:
            user_data[chat_id].pop("email")
            user_data[chat_id].pop("password")
        except Exception as e:
            print(e)
        ask_email(chat_id)
    elif text == '📄 Управление публикациями':
        pages = get_individual_pages(user_data[chat_id]["token"])
        if pages.status_code == 200:
            pages = pages.json()
            if pages:
                for page in pages:
                    # Форматируем вывод информации
                    author_epitaph = page['author_epitaph'] if page['author_epitaph'] else "Не указан"
                    bot.send_message(
                        chat_id,
                        f"📄 <b>Страница памяти</b>\n"
                        f"1. <b>ФИО:</b> {page['full_name']}\n"
                        f"2. <b>Дата рождения:</b> {page['birthday_at']}\n"
                        f"3. <b>Дата смерти:</b> {page['died_at']}\n"
                        f"4. <b>Краткая эпитафия:</b> {page['epitaph'] if page['epitaph'] else 'Не указана'}\n"
                        f"5. <b>Автор эпитафии:</b> {page['author_epitaph'] if page['author_epitaph'] else 'Не указан'}\n"
                        f'<a href="{page["link"]}">Открыть страницу</a>',
                        parse_mode="HTML"
                    )
            else:
                bot.send_message(chat_id, "У вас пока нет созданных страниц памяти.")
        else:
            bot.send_message(chat_id, "Ошибка при запросе данных. Попробуйте позже.")
    elif text == "📝 Заполнить страницу памяти":
        pages = get_individual_pages(user_data[chat_id]["token"])
        if pages.status_code == 200:
            pages = pages.json()
            if pages:
                user_data[chat_id]['pages'] = {}
                markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
                bot.send_message(chat_id, "✅ Страницы памяти получены\n\n")
                message_text = ''
                for i, page in enumerate(pages, start=1):
                    button_text = f"{i} {page['full_name']}"
                    user_data[chat_id]['pages'][button_text.strip()] = page['link']
                    markup.add(KeyboardButton(button_text))

                    # Добавляем данные страницы в сообщение
                    message_text += (
                        f"{i}. ФИО: {page.get('full_name', 'Не указано')}\n"
                        f"   Дата рождения: {page.get('birthday_at', 'Не указана')}\n"
                        f"   Дата смерти: {page.get('died_at', 'Не указана')}\n"
                        f"   Краткая эпитафия: {page.get('epitaph', 'Не указана')}\n"
                        f"   Автор эпитафии: {page.get('author_epitaph', 'Не указан')}\n"
                        f"   Ссылка: {page['link']}\n\n"
                    )

                bot.send_message(
                    chat_id,
                    message_text,
                    reply_markup=markup
                )
            else:
                bot.send_message(chat_id, "У вас пока нет созданных страниц памяти.")
        else:
            bot.send_message(chat_id, "Ошибка при запросе данных. Попробуйте позже.")
    elif text in user_data[519525285]['pages']:
        print(text)
        res = get_memory_page_from_url(user_data[519525285]['pages'][text], user_data[519525285]['token'])
        result = process_memory_page(res)
        print('!!!result:\n', result)
        if "error" in result:
            bot.send_message(chat_id, f"Произошла ошибка: {result['error']}")
        else:
            biography = result["biography"]
            photos = result["photos"]
            main_image = result["main_image"]
            print('photos !!!!!', photos)
            print(main_image)

            # Проверяем наличие данных
            missing_data = []
            if not biography:
                missing_data.append("биография")
            if not main_image:
                missing_data.append("главное фото")
            if not photos:
                missing_data.append("дополнительные фотографии")




            if missing_data:
                missing_info = ", ".join(missing_data)
                bot.send_message(
                    chat_id,
                    f"Страница памяти содержит неполные данные. Отсутствует: {missing_info}. "
                    "Пожалуйста, загрузите недостающие элементы."
                )
                if not main_image or not photos:
                    prompt_for_photos(chat_id)
                if not biography:
                    prompt_for_biography(chat_id)
            else:
                bot.send_message(
                    chat_id,
                    "Страница памяти содержит все необходимые данные. Добавляю в очередь для генерации видео."
                )
                data = {}
                data["biography"] = combine_biography_text(biography)

                data['photos'] = photos
                add_to_video_queue(data, chat_id)

    # bot.send_message(chat_id, "Нажмите /start, чтобы начать заново.")


@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    # Отправляем в консоль информацию о callback
    print(f"Callback data: {call.data}")
    print(f"Message: {call.message}")
    print(f"From user: {call.from_user.id}")

    # Отправляем уведомление пользователю
    bot.answer_callback_query(call.id, text="Callback получен", show_alert=False)

    # Отправляем сообщение в чат для проверки
    bot.send_message(
        call.message.chat.id,
        f"Вы нажали на кнопку с callback_data: {call.data}"
    )


# Подтверждаем данные
def confirm_credentials(chat_id):
    email = user_data[chat_id]["email"]
    password = user_data[chat_id]["password"]
    bot.send_message(
        chat_id,
        f"Проверьте введенные данные:\nЛогин: {email}\nПароль: {password}",
        reply_markup=generate_confirmation_buttons()
    )


# Генерируем кнопки для подтверждения
def generate_confirmation_buttons():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("Продолжить"))
    return markup


# Показываем главное меню
def show_main_menu(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("📝 Заполнить страницу памяти"))
    markup.add(KeyboardButton("📄 Управление публикациями"))
    markup.add(KeyboardButton("➡️ Выполнить аутентификацию"))
    bot.send_message(chat_id, "Ваше главное меню:", reply_markup=markup)


# Заполняем страницу памяти
@bot.message_handler(func=lambda message: message.text == "📝 Заполнить страницу памяти")
def fill_memory_page(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "📝 Запрашиваю страницы памяти...")
    # Здесь выполняем запрос к API для получения страниц памяти
    bot.send_message(chat_id, "✅ Страницы памяти получены\nВаши страницы памяти:\n{список страниц из API}")


# Запускаем бота
bot.infinity_polling()
