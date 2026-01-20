> **⚠️ DISCLAIMER: LEGACY LEARNING PROJECT**
>
> This is a legacy / early learning project. The code works, but does not represent current quality standards. This repository exists to demonstrate learning progress and experimentation.

# AI Tutor Chat

## Project Overview

AI Tutor Chat is an interactive web application that enables users to chat with OpenAI language models. It implements a "Bring Your Own Key" (BYOK) system, allowing users to securely use their own API credentials. The application supports multiple chat sessions, model configuration (temperature, model selection), and local chat history persistence.

## Why this repository exists

This project was created during an early learning phase to experiment, explore ideas, and build a working system end-to-end. The primary goal was to gain hands-on experience with **Streamlit** for UI development and **LangChain** for LLM orchestration, moving from concept to a functional application.

## Current limitations

-   **Project structure is not optimal**: The codebase has mixed responsibilities, with UI and logic often intertwined.
-   **Documentation was partially AI-generated during exploration**: This resulted in a large number of markdown files and some fragmentation in the documentation.
-   **Code quality is inconsistent**: Being an early project, the coding standards and error handling do not meet modern production benchmarks.

## What I would do differently today

-   **Clearer project structure**: I would organize the codebase with a strict separation of concerns (e.g., separate layers for UI, business logic, and data).
-   **Better separation of concerns**: Decouple the Streamlit frontend from the core logic to make the system more testable and maintainable.
-   **Cleaner documentation approach**: Instead of generating many ad-hoc markdown files, I would maintain a centralized and structured documentation base.
-   **Decision logging instead of excessive markdown**: I would use a lightweight decision log (ADR) rather than creating verbose separate files for every change.
-   **More explicit requirements and scope definition**: I would define the scope more rigorously upfront to prevent scope creep and ensure a focused implementation.

## Current status

**Archived / Legacy – not under active development**

---

## Original Documentation (Russian)

# AI Tutor Chat

Интерактивный чат-ассистент на базе LangChain и Streamlit с поддержкой нескольких сессий, настраиваемых параметров модели и персистентного хранения истории.

## Возможности

- 💬 **Множественные чаты**: создавайте и переключайтесь между разными беседами
- 📝 **Пользовательские названия**: автоматическая генерация и ручное переименование чатов
- ⚙️ **Настройка моделей**: выбор модели (GPT-3.5, GPT-4o, etc.) и температуры
- 💾 **Персистентное хранилище**: история чатов сохраняется между перезапусками
- 🎨 **Современный UI**: удобный интерфейс на Streamlit

## Установка

1. Клонируйте репозиторий:

```bash
git clone https://github.com/Johndmn/AI-Tutor.git
cd AI-Tutor
```

2. Создайте виртуальное окружение и активируйте его:

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. Установите зависимости:

```bash
pip install -r requirements.txt
```

4. Создайте файл `.env` и добавьте ваш API ключ OpenAI:

```bash
OPENAI_API_KEY=sk-proj-your-key-here
OPENAI_MODEL_NAME=gpt-3.5-turbo
OPENAI_TEMPERATURE=0.7
OPENAI_AVAILABLE_MODELS=gpt-3.5-turbo,gpt-4o-mini,gpt-4o
```

## Запуск

```bash
streamlit run app.py
```

Приложение откроется в браузере по адресу `http://localhost:8501`

## Структура проекта

```
AI Tutor/
├── app.py                 # Главный файл Streamlit приложения
├── src/
│   ├── __init__.py
│   ├── chat_manager.py    # Менеджер чатов и LangChain логика
│   ├── config.py          # Конфигурация и переменные окружения
│   └── storage.py         # Персистентное хранилище для чатов
├── data/                  # Директория с сохранёнными чатами (создаётся автоматически)
│   └── chats/
├── requirements.txt       # Зависимости Python
├── .env                   # Переменные окружения (не в git)
├── .gitignore
└── README.md
```

## Использование

### Создание нового чата

Нажмите кнопку **"🆕 Новый чат"** в сайдбаре

### Переименование чата

1. Выберите чат из списка
2. Введите новое название в поле **"Название текущего чата"**
3. Нажмите **"💾 Сохранить название"**

### Настройка модели

В разделе **"Настройки"** можно:

- Изменить температуру (0.0-1.0)
- Выбор модели из доступных
- Сбросить настройки к значениям по умолчанию

### Хранение данных

Все чаты автоматически сохраняются в директорию `data/chats/` в формате JSON. При следующем запуске приложения история будет восстановлена.

## Технологии

- **LangChain** - фреймворк для работы с LLM
- **Streamlit** - веб-интерфейс
- **OpenAI API** - языковые модели
- **Python 3.8+**

## Лицензия

MIT

## Автор

[Johndmn](https://github.com/Johndmn)
