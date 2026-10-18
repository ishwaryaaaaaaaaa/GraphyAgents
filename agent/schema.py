"""Constants shared by the memory engine, tools and tests."""

# Fact lifecycle. Only ACTIVE is ever returned by a normal read.
ACTIVE = "active"
SUPERSEDED = "superseded"    # was true, replaced by a newer value
RETRACTED = "retracted"      # was never true
INVALIDATED = "invalidated"  # was true only because of a parent that changed

# Event kinds with a meaning for goals. (The kinds a user may SAY are listed in agent/extract.py.)
ADVANCING_KINDS = ("clean_day", "study_done")  # these count toward a goal (PageRank edges)
RESET_KINDS = ("treat", "slip")                # these reset a streak

# --- people: contacts, interactions, values ---
SOCIAL_KINDS = ("plan", "cancel", "favor", "argument", "apology", "ghosted", "celebration",
                "made_up")
KIND_PHRASES = {"plan": "made plans", "cancel": "cancelled", "favor": "helped you",
                "argument": "had an argument", "apology": "apologised", "ghosted": "went quiet",
                "celebration": "celebrated with you", "made_up": "made up"}
TONES = ("warm", "neutral", "cold", "tense")
CONTACT_STATUS = ("fine", "strained")
RELATIONS = ("friend", "colleague", "sister", "brother", "cousin", "roommate", "mom", "dad")
VALUE_TAGS = ("honesty", "show_up", "peace", "self_respect", "loyalty")
VALUE_WORDS = {"honesty": "honesty", "show_up": "showing up", "peace": "peace",
               "self_respect": "self-respect", "loyalty": "loyalty"}
FACT_SOURCES = ("typed", "extracted", "hearsay")

CASCADE_MAX_HOPS = 6

INDEXES = (
    "CREATE INDEX FOR (f:Fact) ON (f.key)",
    "CREATE INDEX FOR (f:Fact) ON (f.status)",
    "CREATE INDEX FOR (g:Goal) ON (g.tag)",
    "CREATE INDEX FOR (e:Event) ON (e.tag)",
    "CREATE INDEX FOR (e:Event) ON (e.day)",
)
