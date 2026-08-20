app_name = "hrmsadapter"
app_title = "HRMS Adapter"
app_publisher = "Suvaidyam"
app_description = "Mobile middleware adapter for ERPNext HRMS — Flutter app layer"
app_email = "tech@suvaidyam.com"
app_license = "mit"
app_icon = "octicon octicon-device-mobile"
app_color = "#4A90E2"

required_apps = ["erpnext", "hrms"]

# Installation
after_install = "hrmsadapter.install.after_install"
before_uninstall = "hrmsadapter.install.before_uninstall"

# -------------------------------------------------------------------------
# Document Events — Workflow Notification Triggers  [Phase 7]
# -------------------------------------------------------------------------
doc_events = {
	"Leave Application": {
		"on_submit": "hrmsadapter.services.notification_service.on_leave_application_submit",
		"on_update": "hrmsadapter.services.notification_service.on_leave_application_update",
		"on_cancel": "hrmsadapter.services.notification_service.on_leave_application_cancel",
	},
	"Expense Claim": {
		"on_submit": "hrmsadapter.services.notification_service.on_expense_claim_submit",
		"on_update": "hrmsadapter.services.notification_service.on_expense_claim_update",
	},
	"Shift Request": {
		"on_submit": "hrmsadapter.services.notification_service.on_shift_request_submit",
		"on_update": "hrmsadapter.services.notification_service.on_shift_request_update",
	},
	"Attendance Request": {
		"on_submit": "hrmsadapter.services.notification_service.on_attendance_request_submit",
	},
	"Travel Request": {
		"on_submit": "hrmsadapter.services.notification_service.on_travel_request_submit",
		"on_update": "hrmsadapter.services.notification_service.on_travel_request_update",
	},
	"Loan Application": {
		"on_submit": "hrmsadapter.services.notification_service.on_loan_application_submit",
		"on_update": "hrmsadapter.services.notification_service.on_loan_application_update",
	},
	"Appraisal": {
		"on_submit": "hrmsadapter.services.notification_service.on_appraisal_submit",
	},
	"Employee Advance": {
		"on_update": "hrmsadapter.services.notification_service.on_advance_update",
	},
	"User": {
		"on_update": "hrmsadapter.services.auth_service.on_user_update",
	},
}

# -------------------------------------------------------------------------
# Scheduled Tasks  [Phase 7 / Phase 10]
# -------------------------------------------------------------------------
scheduler_events = {
	"all": [
		"hrmsadapter.tasks.notification_queue.process_notification_queue",
	],
	"hourly": [
		"hrmsadapter.tasks.token_cleanup.cleanup_blacklisted_tokens",
	],
	"daily": [
		"hrmsadapter.tasks.token_cleanup.expire_inactive_devices",
	],
}

# -------------------------------------------------------------------------
# Request Lifecycle  [Phase 2 / Phase 10]
# -------------------------------------------------------------------------
before_request = ["hrmsadapter.decorators.auth.validate_mobile_jwt_if_present"]

# -------------------------------------------------------------------------
# Export Fixtures  [Phase 10]
# -------------------------------------------------------------------------

fixtures = [
	# {
    # "dt": "Custom DocPerm",
    # "filters": {
    #   "parent": "HRMS Mobile Settings",
	# 	}
	# },
	#   {
    #     "dt": "Workspace",
    #     "filters": [
    #         ["name", "=", "Mobile App Login"]
    #     ]
    # },
    # {
    #     "dt": "Custom HTML Block",
    #     "filters": [
    #         ["name", "=", "QR Code"]
    #     ]
    # }
]