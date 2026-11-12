"""`python manage.py run_worker`: this service's Kafka worker.

What it reads and how it reacts comes from settings.MESSAGING, so the same command
serves every Django service.
"""

import logging

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils.module_loading import import_string

from messaging.kafka import Worker


class Command(BaseCommand):
    help = "Consume this service's Kafka topics, publish its outbox, and run its periodic jobs."

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        config = settings.MESSAGING
        handlers = import_string(config["HANDLERS"]) if config.get("HANDLERS") else {}
        periodic = [(every, import_string(path)) for every, path in config.get("PERIODIC", [])]
        Worker(group=config["GROUP"], topics=config.get("TOPICS", []), handlers=handlers, periodic=periodic).run()
