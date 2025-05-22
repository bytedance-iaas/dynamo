from components.frontend import Frontend
from components.processor import Processor
from components.worker import VllmWorker

Frontend.link(Processor).link(VllmWorker)