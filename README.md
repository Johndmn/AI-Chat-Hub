# AI Tutor Chat

> **⚠️ NOTICE: LEGACY / LEARNING PROJECT**
>
> This repository contains an early-stage project created for learning purposes. While the code is functional, it does not represent current professional standards or best practices. It is preserved here to demonstrate the progression of my skills and experimentation with technologies like Streamlit and LangChain.

## Project Overview

**AI Tutor Chat** is a web-based chat application that interfaces with OpenAI's GPT models. Built using **Streamlit** and **LangChain**, it allows users to conduct multi-session conversations with persistent history.

**Note:** The application's user interface and internal comments are primarily in Russian.

Key capabilities:
-   **Session Management**: Create, rename, and manage multiple independent chat sessions.
-   **Model Configuration**: Customize model parameters (temperature) and switch between GPT-3.5 and GPT-4 families.
-   **Bring Your Own Key (BYOK)**: Secure, session-based input of OpenAI API keys.
-   **Persistence**: Auto-saving of chat history to local JSON storage.
-   **Utilities**: Built-in token counting and chat export functionality.

## Purpose & Context

This project was built to explore the end-to-end development of a GenAI application. It served as a sandbox to:
-   Master the **LangChain** library for LLM orchestration.
-   Experiment with **Streamlit** for rapid UI prototyping and state management.
-   Implement a "Bring Your Own Key" (BYOK) architecture.
-   Deliver a functional product from scratch.

## Current Limitations

As an experimental project, several limitations exist:
-   **Architecture**: The codebase lacks strict separation of concerns, with UI and logic often intertwined.
-   **Documentation**: Existing documentation is fragmented and partially AI-generated.
-   **Storage**: Chat history is saved to local JSON files, which is not suitable for production or concurrent users.
-   **Localization**: The interface is hardcoded in Russian, restricting usage to Russian speakers.
-   **Code Consistency**: Error handling and coding styles are inconsistent.

## Retrospective: Improvements for Production

If I were to rebuild this today, I would prioritize:
1.  **Modular Architecture**: Enforcing a clean separation between the frontend, business logic, and data layers.
2.  **Robust State Management**: Decoupling application state from the UI framework.
3.  **Internationalization (i18n)**: Supporting multiple languages via resource files.
4.  **Testing Strategy**: Implementing comprehensive unit and integration tests.
5.  **Documentation Standards**: Maintaining a clear decision log and manual documentation for critical paths.

## Current Status

🛑 **Archived / Legacy – not under active development.**

---

## Appendix: Original Documentation (Russian)

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
