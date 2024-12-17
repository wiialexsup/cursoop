from itertools import count

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from ics import Calendar
from datetime import datetime, timedelta
import pytz


class ScheduleBot:
    # Константы состояний
    MAIN_MENU, NEAR_LESSON, DAY_SCHEDULE, TOMORROW_SCHEDULE = range(4)
    MAX_MESSAGE_LENGTH = 4096

    days_of_week = {
        "понедельник": 0,
        "вторник": 1,
        "среда": 2,
        "четверг": 3,
        "пятница": 4,
        "суббота": 5,
        "воскресенье": 6
    }

    WEEK_SCHEDULE = 5

    def __init__(self, token: str):
        self.application = Application.builder().token(token).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                self.MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.main_menu)],
                self.NEAR_LESSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.near_lesson)],
                self.DAY_SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.day_schedule)],
                self.TOMORROW_SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.tomorrow_schedule)],
                self.WEEK_SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.week_schedule)],
            },
            fallbacks=[CommandHandler("cancel", self.start)],
        )

        self.application.add_handler(conv_handler)

    # Функция для загрузки расписания из .ics
    def load_calendar(self, group_file):

        try:
            with open(group_file, 'r', encoding='utf-8') as file:
                return Calendar(file.read())
        except FileNotFoundError:
            return None

    # Вспомогательная функция для фильтрации событий
    def filter_events(self, events, date=None, week_number=None):
        if date:
            events = [event for event in events if event.begin.date() == date.date()]
        if week_number is not None:
            events = [
                event for event in events if (event.begin.isocalendar()[1] % 2 == week_number % 2)
            ]
        return sorted(events, key=lambda e: e.begin)

    def filter_events_by_day_and_week(self, calendar, target_day, week_number):
        events = []

        # Go through all events in the calendar
        for event in calendar.events:
            # Check if the event has a recurrence rule (RRULE)
            if hasattr(event, 'rrule') and event.rrule:
                # Process recurring events
                for dt in event.rrule.between(event.begin, event.end):
                    # Compare if the day of the event matches the target day
                    if dt.weekday() == target_day:
                        events.append(event)
            else:
                # Process non-recurring events
                if event.begin.weekday() == target_day:
                    events.append(event)

        # Filter based on week number (even or odd weeks)
        filtered_events = [event for event in events if event.begin.isocalendar()[1] % 2 == week_number % 2]

        return filtered_events

    # Вспомогательная функция для форматирования событий
    def format_event(self, event):
        description_lines = event.description.split("\n")[0]
        parts = description_lines.split(", ")

        auditorium = "Не указана"
        teacher = "Не указан"

        if len(parts) == 2:
            auditorium, teacher = parts[0].strip(), parts[1].strip()
        elif len(parts) == 1:
            if parts[0].replace(" ", "").isdigit():
                auditorium = parts[0].strip()
            else:
                teacher = parts[0].strip()

        return (
            f"{event.begin.format('dddd, HH:mm')} - {event.name}\n"
            f"Аудитория: {auditorium}\n"
            f"Преподаватель: {teacher}\n\n"
        )


    # Стартовое меню
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

        reply_keyboard = [
            ["Ближайшее занятие", "Расписание на день"],
            ["Расписание на завтра", "Расписание на неделю"],
            ["Стоп"]
        ]
        await update.message.reply_text(
            "Выберите доступные действия:",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
        )
        return self.MAIN_MENU

    # Обработка выбора команды
    async def main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text

        if text == "Ближайшее занятие":
            await update.message.reply_text("Введите номер недели и номер группы (пример: 1 2129)\nДля возврата напишите '0'",
                                            reply_markup=ReplyKeyboardRemove())
            return self.NEAR_LESSON
        elif text == "Расписание на день":
            await update.message.reply_text("Введите день, номер недели и номер группы (пример: понедельник 1 2129)\nДля возврата напишите '0'",
                                            reply_markup=ReplyKeyboardRemove())
            return self.DAY_SCHEDULE
        elif text == "Расписание на завтра":
            await update.message.reply_text("Введите номер недели и группу(пример: 1 2129)\nДля возврата напишите '0'",
                                            reply_markup=ReplyKeyboardRemove())
            return self.TOMORROW_SCHEDULE
        elif text == "Расписание на неделю":
            await update.message.reply_text("Введите номер недели и номер группы (пример: 1 2129)\nДля возврата напишите '0'",
                                            reply_markup=ReplyKeyboardRemove())
            return self.WEEK_SCHEDULE
        elif text == "Стоп":
            await update.message.reply_text("Бот остановлен.\nДля перезапуска нажмите /start.",
                                            reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        else:
            await update.message.reply_text("Пожалуйста, выберите действие из меню.")
            return self.MAIN_MENU

    # Расписание на неделю
    async def week_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if update.message.text.lower() == "0":
            await update.message.reply_text(
                "Действие отменено. Вы вернулись в главное меню.")
            return await self.start(update, context)
        args = update.message.text.split()
        if len(args) < 2:
            await update.message.reply_text(
                "Введите номер недели и номер группы (пример: 1 2129):\nДля возврата напишите '0'"
            )
            return self.WEEK_SCHEDULE

        try:
            week_number, group_number = int(args[0]), args[1]
        except ValueError:
            await update.message.reply_text(
                "Неверный формат. Введите номер недели и номер группы.\nДля возврата напишите '0'")
            return self.WEEK_SCHEDULE

        group_file = f"calendars\\calendar-group-{group_number}.ics"

        # Загрузка расписания
        calendar = self.load_calendar(group_file)
        if not calendar:
            await update.message.reply_text(f"Файл {group_file} не найден или повреждён.\nВведите корректные данные или введите 0 для выхода в меня.")
            return await self.start(update, context)

        # Фильтрация событий
        events = [
            event for event in calendar.events
            if (event.begin.isocalendar()[1] % 2 == week_number % 2)
        ]

        # Форматированный вывод
        if events:
            response = f"Расписание для группы {group_number} на {'чётную' if week_number == 1 else 'нечётную'} неделю:\n\n"
            for event in sorted(events, key=lambda e: e.begin):
                # Разделяем поле DESCRIPTION
                description_lines = event.description.split("\n")[0]  # Берём первую строку из описания
                parts = description_lines.split(", ")  # Пробуем разделить по запятой и пробелу

                # Инициализируем значения по умолчанию
                auditorium = "Не указана"
                teacher = "Не указан"

                if len(parts) == 2:  # Если указаны обе части
                    auditorium, teacher = parts[0].strip(), parts[1].strip()
                elif len(parts) == 1:  # Если только одна часть
                    if parts[0].replace(" ", "").isdigit():  # Если это похоже на аудиторию
                        auditorium = parts[0].strip()
                    else:  # Иначе это преподаватель
                        teacher = parts[0].strip()

                # Формируем текст для вывода
                response += (
                    f"{event.begin.format('dddd, HH:mm')} - {event.name}\n"
                    f"Аудитория: {auditorium}\n"
                    f"Преподаватель: {teacher}\n\n"
                )

            # Отправляем сообщение частями, если оно слишком длинное
            for chunk in [response[i:i + self.MAX_MESSAGE_LENGTH] for i in range(0, len(response), self.MAX_MESSAGE_LENGTH)]:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(f"Занятий для группы {group_number} на {'чётную' if week_number == 1 else 'нечётную'} неделю не найдено.")
        return await self.start(update, context)

    async def day_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if update.message.text.lower() == "0":
            await update.message.reply_text(
                "Действие отменено. Вы вернулись в главное меню.")
            return await self.start(update, context)
        args = update.message.text.split()
        if len(args) < 3:
            await update.message.reply_text(
                "Введите день, номер недели и номер группы (пример: понедельник 1 2129)\nДля возврата напишите '0'"
            )
            return self.DAY_SCHEDULE

        try:
            day, week_number, group_number = args[0].lower(), int(args[1]), args[2]
        except ValueError:
            await update.message.reply_text(
                "Неверный формат. Введите день, номер недели и номер группы.\nДля возврата напишите '0'")
            return self.DAY_SCHEDULE

        group_file = f"calendars\\calendar-group-{group_number}.ics"
        calendar = self.load_calendar(group_file)

        if not calendar:
            await update.message.reply_text(f"Файл {group_file} не найден или повреждён.\nВведите корректные данные или введите 0 для выхода в меня.")
            return self.DAY_SCHEDULE

        target_day = self.days_of_week.get(day)

        if target_day is None:
            await update.message.reply_text(
                "Некорректный день недели. Пожалуйста, используйте один из: понедельник, вторник, ...\nДля возврата напишите '0'")
            return self.DAY_SCHEDULE

        # Фильтрация событий с учётом RRULE и чётности недели
        events = self.filter_events_by_day_and_week(calendar, target_day, week_number)

        if events:
            # Сортировка событий по времени начала
            events_sorted = sorted(events, key=lambda event: event.begin)

            response = f"Расписание на {day.capitalize()} для группы {group_number}:\n"
            for event in events_sorted:
                description_lines = event.description.split("\n")[0]
                parts = description_lines.split(", ")

                auditorium = "Не указана"
                teacher = "Не указан"
                if len(parts) == 2:
                    auditorium, teacher = parts[0].strip(), parts[1].strip()
                elif len(parts) == 1:
                    if parts[0].replace(" ", "").isdigit():
                        auditorium = parts[0].strip()
                    else:
                        teacher = parts[0].strip()

                response += (
                    f"{event.begin.format('HH:mm')} - {event.name}\n"
                    f"Аудитория: {auditorium}\n"
                    f"Преподаватель: {teacher}\n\n"
                )
            await update.message.reply_text(response)
        else:
            await update.message.reply_text(f"Для группы {group_number} занятий на {day.capitalize()} не найдено.")

        return await self.start(update, context)

    async def tomorrow_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if update.message.text.lower() == "0":
            await update.message.reply_text(
                "Действие отменено. Вы вернулись в главное меню.")
            return await self.start(update, context)

        args = update.message.text.split()
        if len(args) < 2:
            await update.message.reply_text(
                "Введите номер недели и номер группы (пример: 1 2129)\nДля возврата напишите '0'"
            )
            return self.TOMORROW_SCHEDULE

        try:
            week_number, group_number = int(args[0]), args[1]
        except ValueError:
            await update.message.reply_text(
                "Неверный формат. Введите номер недели и номер группы.\nДля возврата напишите '0'")
            return self.TOMORROW_SCHEDULE

        group_file = f"calendars\\calendar-group-{group_number}.ics"
        calendar = self.load_calendar(group_file)

        if not calendar:
            await update.message.reply_text(f"Файл {group_file} не найден или повреждён.\nВведите корректные данные или введите 0 для выхода в меня.")
            return self.TOMORROW_SCHEDULE
        now = datetime.now(pytz.timezone("Europe/Moscow"))
        day = now + timedelta(days=1)
        target_day = day.weekday()

        # Фильтрация событий с учётом RRULE и чётности недели
        events = self.filter_events_by_day_and_week(calendar, target_day, week_number)

        if events:
            # Сортировка событий по времени начала
            events_sorted = sorted(events, key=lambda event: event.begin)

            response = f"Расписание на завтра для группы {group_number}:\n"
            for event in events_sorted:
                description_lines = event.description.split("\n")[0]
                parts = description_lines.split(", ")

                auditorium = "Не указана"
                teacher = "Не указан"
                if len(parts) == 2:
                    auditorium, teacher = parts[0].strip(), parts[1].strip()
                elif len(parts) == 1:
                    if parts[0].replace(" ", "").isdigit():
                        auditorium = parts[0].strip()
                    else:
                        teacher = parts[0].strip()

                response += (
                    f"{event.begin.format('HH:mm')} - {event.name}\n"
                    f"Аудитория: {auditorium}\n"
                    f"Преподаватель: {teacher}\n\n"
                )
            await update.message.reply_text(response)
        else:
            await update.message.reply_text(f"Для группы {group_number} занятий на завтра не найдено.")

        return await self.start(update, context)

    async def near_lesson(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        if update.message.text.lower() == "0":
            await update.message.reply_text(
                "Действие отменено. Вы вернулись в главное меню.")
            return await self.start(update, context)

        args = update.message.text.split()
        if len(args) < 2:
            await update.message.reply_text(
                "Введите номер недели и номер группы (пример: 1 2129)\nДля возврата напишите '0'"
            )
            return self.NEAR_LESSON

        try:
            week_number, group_number = int(args[0]), args[1]
        except ValueError:
            await update.message.reply_text(
                "Неверный формат. Введите номер недели и номер группы.\nДля возврата напишите '0'")
            return self.NEAR_LESSON

        group_file = f"calendars\\calendar-group-{group_number}.ics"
        calendar = self.load_calendar(group_file)

        if not calendar:
            await update.message.reply_text(f"Файл {group_file} не найден или повреждён.\nВведите корректные данные или введите 0 для выхода в меня.")
            return self.NEAR_LESSON

        now = datetime.now(pytz.timezone("Europe/Moscow"))
        today = now.weekday()
        current_time = now.time()

        # Фильтрация событий с учётом RRULE и чётности недели
        events = self.filter_events_by_day_and_week(calendar, today, week_number)

        if events:
            # Сортировка событий по времени начала
            events_sorted = sorted(events, key=lambda event: event.begin.time())

            # Найти ближайшее событие по времени
            next_event = next(
                (event for event in events_sorted if event.begin.time() > current_time), None
            )

            if next_event:
                description_lines = next_event.description.split("\n")[0]
                parts = description_lines.split(", ")

                auditorium = "Не указана"
                teacher = "Не указан"
                if len(parts) == 2:
                    auditorium, teacher = parts[0].strip(), parts[1].strip()
                elif len(parts) == 1:
                    if parts[0].replace(" ", "").isdigit():
                        auditorium = parts[0].strip()
                    else:
                        teacher = parts[0].strip()

                response = (
                    f"Ближайшее занятие группы {group_number}:\n"
                    f"{next_event.begin.format('HH:mm')} - {next_event.name}\n"
                    f"Аудитория: {auditorium}\n"
                    f"Преподаватель: {teacher}\n"
                )
                await update.message.reply_text(response)
            else:
                await update.message.reply_text(
                    f"Для группы {group_number} сегодня больше нет занятий."
                )
        else:
            await update.message.reply_text(f"Для группы {group_number} занятий не найдено.")

        return await self.start(update, context)


if __name__ == "__main__":
    bot_token = "TOKEN"
    bot = ScheduleBot(bot_token)
    bot.application.run_polling()
