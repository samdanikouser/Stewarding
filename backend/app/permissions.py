MANAGER = "manager"
SUPERVISOR = "supervisor"
STEWARD = "steward"

ALL_PERMISSIONS = [
    "dashboard.view",
    "employee.view", "employee.manage",
    "attendance.self", "attendance.view", "attendance.correct", "attendance.absence",
    "roster.view", "roster.manage",
    "checklist.view", "checklist.complete", "checklist.verify", "checklist.configure",
    "task.assign",
    "temp.view", "temp.record", "temp.review",
    "equipment.view", "equipment.manage",
    "inventory.module", "inventory.view", "inventory.count", "inventory.manage",
    "stock.transfer", "stock.approve",
    "breakage.view", "breakage.report", "breakage.review", "breakage.approve",
    "lot.view", "lot.receive", "lot.split", "lot.manage",
    "notification.view", "training.view",
    "report.view", "report.export",
    "settings.manage",
    "audit.view",
]

SUPERVISOR_PERMISSIONS = [
    "dashboard.view", "employee.view", "attendance.self", "attendance.view", "attendance.absence", "roster.view",
    "checklist.view", "checklist.complete", "checklist.verify", "task.assign",
    "temp.view", "temp.record", "temp.review", "equipment.view",
    "inventory.module", "inventory.view", "inventory.count", "stock.transfer",
    "breakage.view", "breakage.report", "breakage.review",
    "lot.view", "lot.receive",
    "notification.view", "training.view", "report.view",
]

STEWARD_PERMISSIONS = [
    "dashboard.view", "attendance.self", "checklist.view", "checklist.complete",
    "temp.view", "temp.record", "inventory.view", "breakage.report", "notification.view", "training.view",
]

ROLE_PERMISSIONS = {
    MANAGER: ALL_PERMISSIONS,
    SUPERVISOR: SUPERVISOR_PERMISSIONS,
    STEWARD: STEWARD_PERMISSIONS,
}

# Tiers a custom role can behave like; the manager tier stays with the built-in manager role.
CUSTOM_TIERS = (SUPERVISOR, STEWARD)

# Shown when choosing what a role may do: group, then (permission, label).
PERMISSION_CATALOG = [
    ("Dashboard", [("dashboard.view", "See the dashboard")]),
    ("People", [("employee.view", "View employees"), ("employee.manage", "Add and edit employees"),
                ("attendance.self", "Check in and out"), ("attendance.view", "View attendance"),
                ("attendance.correct", "Correct attendance"), ("attendance.absence", "Record absences"),
                ("roster.view", "View the roster"), ("roster.manage", "Edit the roster")]),
    ("Checklists", [("checklist.view", "View checklists"), ("checklist.complete", "Complete tasks"),
                    ("checklist.verify", "Verify tasks"), ("checklist.configure", "Configure checklists"),
                    ("task.assign", "Assign tasks")]),
    ("Monitoring", [("temp.view", "View monitoring"), ("temp.record", "Record readings"), ("temp.review", "Review readings"),
                    ("equipment.view", "View monitoring setup"), ("equipment.manage", "Edit monitoring setup")]),
    ("Inventory", [("inventory.module", "Open inventory"), ("inventory.view", "View items"),
                   ("inventory.count", "Count stock and set location minimums"), ("inventory.manage", "Add and edit items"),
                   ("stock.transfer", "Post stock and request transfers"), ("stock.approve", "Approve transfers")]),
    ("Breakage", [("breakage.view", "View breakage"), ("breakage.report", "Report breakage"),
                  ("breakage.review", "Review breakage"), ("breakage.approve", "Approve high-value breakage")]),
    ("Food traceability", [("lot.view", "View lots and traces"), ("lot.receive", "Receive food and create lots"),
                           ("lot.split", "Split lots into portions (butcher)"), ("lot.manage", "Hold, discard and set shelf-life rules")]),
    ("Training", [("training.view", "Take the training assigned to them")]),
    ("Reports and admin", [("notification.view", "See tasks and notifications"), ("report.view", "View reports"),
                           ("report.export", "Export reports"), ("settings.manage", "Manage settings and roles"),
                           ("audit.view", "View audit logs")]),
]

# key, label, permission that grants sight of the module
MODULES = [
    ("dashboard", "Dashboard", "dashboard.view"),
    ("employees", "Employees", "employee.view"),
    ("check-in", "Check in & out", "attendance.self"),
    ("my-schedule", "My Schedule", "attendance.self"),
    ("attendance", "Attendance", "attendance.self"),
    ("roster", "Shift & Duty Roster", "roster.view"),
    ("checklists", "Checklists", "checklist.view"),
    ("monitoring", "Monitoring", "temp.view"),
    ("equipment", "Monitoring Setup", "equipment.view"),
    ("inventory", "Inventory", "inventory.module"),
    ("stock-movements", "Stock Movements & Transfers", "stock.transfer"),
    ("breakage", "Breakage & Damage Logs", "breakage.report"),
    ("traceability", "Food Traceability", "lot.view"),
    ("training", "Training", "training.view"),
    ("tasks", "Tasks & Notifications", "notification.view"),
    ("reports", "Reports & Analytics", "report.view"),
    ("settings", "Settings", "settings.manage"),
    ("audit", "Audit Logs", "audit.view"),
]
