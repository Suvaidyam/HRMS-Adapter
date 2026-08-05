def process_notification_queue():
	from hrmsadapter.services.notification_service import process_notification_queue as _run
	_run()
