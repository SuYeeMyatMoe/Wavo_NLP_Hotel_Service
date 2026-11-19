"""Public local-demo credentials; hosted guests use Supabase Auth reservations."""

GUESTS = {
    "guest": ("guest@wavo.demo", "Guest305!", "demo-guest", "305"),
    "guest402": ("guest402@wavo.demo", "Guest402!", "demo-guest-402", "402"),
    "guest512": ("guest512@wavo.demo", "Guest512!", "demo-guest-512", "512"),
}

ACCOUNTS = {key: values[:3] for key, values in GUESTS.items()}
ACCOUNTS.update(
    {
        "staff": ("maintenance@wavo.demo", "Staff123!", "demo-maintenance"),
        "backup": ("backup@wavo.demo", "Staff123!", "demo-maintenance-2"),
        "supervisor": ("staff@wavo.demo", "Staff123!", "demo-staff"),
        "reception": ("reception@wavo.demo", "Staff123!", "demo-reception"),
        "housekeeping": ("housekeeping@wavo.demo", "Staff123!", "demo-housekeeping"),
    }
)
PREVIEW_ACTORS = {account[2] for account in ACCOUNTS.values()}

# Explicit demo-only availability, not a claim about a real hotel's roster.
ROSTER = [
    (
        "staff",
        "Aung · Maintenance",
        "Maintenance",
        ["Air conditioning", "Plumbing", "Electrical"],
        3,
    ),
    (
        "backup",
        "Maya · Maintenance",
        "Maintenance",
        ["Air conditioning", "Plumbing", "Electrical"],
        3,
    ),
    (
        "reception",
        "Lin · Reception",
        "Front Desk",
        ["Reception review", "Wi-Fi", "Billing", "Food and drink"],
        12,
    ),
    ("housekeeping", "Nora · Housekeeping", "Housekeeping", ["Housekeeping"], 5),
    (
        "supervisor",
        "Supervisor · Reception",
        "Front Desk",
        ["Reception review", "Wi-Fi", "Billing", "Food and drink"],
        12,
    ),
]
