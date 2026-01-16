# AI Tutor Chat

> **⚠️ DISCLAIMER: LEGACY LEARNING PROJECT**
>
> This repository represents an early-stage learning project. The code is functional but does not reflect current quality standards or my current skill level. It has been preserved here to demonstrate my learning progress and experimentation.

## Project Overview

AI Tutor Chat is an interactive web application built with **Streamlit** and **LangChain**. It provides a user-friendly interface for chatting with OpenAI's language models (GPT-3.5, GPT-4).

Key features include:
-   **Multi-session management**: Create, rename, and switch between multiple chat histories.
-   **Customizable Settings**: Adjust model parameters (temperature) and switch between available models.
-   **BYOK (Bring Your Own Key)**: Users can securely input their own OpenAI API key for session-based usage.
-   **Persistent History**: Chat sessions are stored locally, preserving context between reloads.
-   **Utility Features**: Token counting, chat export to text, and "quick prompt" templates for common tasks.

## Why this repository exists

This project was created during an early learning phase to experiment, explore ideas, and build a working system end-to-end. The primary goals were to:
-   Explore the **LangChain** ecosystem.
-   Understand state management in **Streamlit**.
-   Build a functional "Bring Your Own Key" system to safely share the app without exposing personal API quotas.
-   Deliver a complete, end-to-end working system.

## Current limitations

As a legacy learning project, it has several known limitations:
-   **Project Structure**: The project structure is not optimal, with mixed responsibilities in the main application file.
-   **Documentation**: The documentation was partially AI-generated during exploration, leading to some fragmentation across multiple files.
-   **Code Quality**: The code quality and error handling are inconsistent compared to production-grade software.
-   **Storage**: Local JSON file storage is used for simplicity, which is not scalable for multi-user deployments.

## What I would do differently today

With more experience, I would improve the following aspects:
-   **Clearer Project Structure**: Strictly separate UI, business logic, and data access layers.
-   **Better Separation of Concerns**: Fully decouple the Streamlit frontend from the LangChain logic.
-   **Cleaner Documentation Approach**: Use a centralized documentation system and maintain a decision log instead of scattered markdown files.
-   **Explicit Requirements**: Define scope and requirements more clearly upfront to avoid "feature creep."
-   **Testing**: Implement a proper testing suite (Unit/Integration) which is currently absent.

## Current status

🛑 **Archived / Legacy - Not under active development.**

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
