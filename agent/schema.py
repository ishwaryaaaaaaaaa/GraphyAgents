"""Constants shared by the memory engine, tools and tests."""

# Fact lifecycle. Only ACTIVE is ever returned by a normal read.
ACTIVE = "active"
SUPERSEDED = "superseded"    # was true, replaced by a newer value
RETRACTED = "retracted"      # was never true
INVALIDATED = "invalidated"  # was true only because of a parent that changed
STATUSES = (ACTIVE, SUPERSEDED, RETRACTED, INVALIDATED)

# Fact key shapes: single-valued slots, per-item slots (likes:x), derived slots.
SINGLE_KEYS = ("diet_style", "lives_in", "wake_time")
ITEM_PREFIXES = ("likes:", "dislikes:")
DERIVED_KEYS = ("mess_meals_available",)  # plus avoid_<item>_orders
SHORT_LIVED_KEYS = ("mood", "craving_today")  # these decay (ttl_days)

EVENT_KINDS = ("clean_day", "slip", "treat", "study_done", "override")
ADVANCING_KINDS = ("clean_day", "study_done")  # these count toward a goal (PageRank edges)
RESET_KINDS = ("treat", "slip")                # these reset a streak
PROMISE_STATUSES = ("open", "kept", "broken")

# --- people: contacts, interactions, values ---
SOCIAL_KINDS = ("plan", "cancel", "favor", "argument", "apology", "ghosted", "celebration",
                "made_up")
TONES = ("warm", "neutral", "cold", "tense")
CONTACT_STATUS = ("fine", "strained")
RELATIONS = ("friend", "colleague", "sister", "brother", "cousin", "roommate", "mom", "dad")
VALUE_TAGS = ("honesty", "show_up", "peace", "self_respect", "loyalty")
FACT_SOURCES = ("typed", "extracted", "hearsay")

CASCADE_MAX_HOPS = 6

INDEXES = (
    "CREATE INDEX FOR (f:Fact) ON (f.key)",
    "CREATE INDEX FOR (f:Fact) ON (f.status)",
    "CREATE INDEX FOR (g:Goal) ON (g.tag)",
    "CREATE INDEX FOR (e:Event) ON (e.tag)",
    "CREATE INDEX FOR (e:Event) ON (e.day)",
)
