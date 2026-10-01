# -*- coding: utf-8 -*-
"""Напоминания «проверить тех. статус»: чистый SQLite на временной БД."""
import datetime
import os
import tempfile
import unittest

import tech_reminders


class TechRemindersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = tech_reminders.DB_PATH
        tech_reminders.DB_PATH = os.path.join(self._tmp.name, 'r.db')

    def tearDown(self):
        tech_reminders.DB_PATH = self._orig
        self._tmp.cleanup()

    def test_add_and_for_ticker(self):
        rid = tech_reminders.add('avgo', '2026-10-07', note='wait READY')
        self.assertIsNotNone(rid)
        items = tech_reminders.for_ticker('AVGO')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['due_date'], '2026-10-07')
        self.assertEqual(items[0]['note'], 'wait READY')
        self.assertEqual(items[0]['notified'], 0)

    def test_one_reminder_per_ticker_replaces(self):
        tech_reminders.add('AVGO', '2026-10-07')
        tech_reminders.add('AVGO', '2026-10-14')
        items = tech_reminders.for_ticker('AVGO')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['due_date'], '2026-10-14')

    def test_empty_ticker_ignored(self):
        self.assertIsNone(tech_reminders.add('', '2026-10-07'))
        self.assertIsNone(tech_reminders.add('AVGO', ''))

    def test_due_events_only_past_or_today(self):
        today = datetime.date.today()
        past = (today - datetime.timedelta(days=1)).isoformat()
        future = (today + datetime.timedelta(days=3)).isoformat()
        tech_reminders.add('AVGO', past)
        tech_reminders.add('MSFT', future)
        due = tech_reminders.due_events()
        self.assertEqual([d['ticker'] for d in due], ['AVGO'])

    def test_mark_notified_hides(self):
        today = datetime.date.today().isoformat()
        rid = tech_reminders.add('AVGO', today)
        due = tech_reminders.due_events()
        self.assertEqual(len(due), 1)
        tech_reminders.mark_notified([d['id'] for d in due])
        self.assertEqual(tech_reminders.due_events(), [])
        self.assertEqual(tech_reminders.for_ticker('AVGO')[0]['notified'], 1)
        self.assertEqual(rid, tech_reminders.for_ticker('AVGO')[0]['id'])

    def test_remove(self):
        rid = tech_reminders.add('AVGO', '2026-10-07')
        tech_reminders.remove(rid)
        self.assertEqual(tech_reminders.for_ticker('AVGO'), [])

    def test_remove_for_ticker(self):
        tech_reminders.add('AVGO', '2026-10-07')
        tech_reminders.remove_for_ticker('avgo')
        self.assertEqual(tech_reminders.for_ticker('AVGO'), [])

    def test_reminder_text(self):
        r = {'ticker': 'AVGO', 'due_date': '2026-10-07', 'note': 'wait READY'}
        txt = tech_reminders.reminder_text(r)
        self.assertIn('AVGO', txt)
        self.assertIn('2026-10-07', txt)
        self.assertIn('wait READY', txt)

    def test_all_reminders_sorted(self):
        tech_reminders.add('MSFT', '2026-10-14')
        tech_reminders.add('AVGO', '2026-10-07')
        self.assertEqual([r['ticker'] for r in tech_reminders.all_reminders()],
                         ['AVGO', 'MSFT'])


if __name__ == '__main__':
    unittest.main()
