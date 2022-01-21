# Just a fake enum and namespace to keep status-related things in. If we use a
# real Enum, Django weirdly doesn't want to display the human-readable version.

INITIAL_IDEA = "II"
AWAITING_EDITOR = "AE"
NEEDS_DISCUSSION = "ND"
WAITING_FOR_ROUND = "WR"
AWAITING_REVIEW = "AR"
IDEA_IN_DEVELOPMENT = "ID"
# IDEA_IN_DEVELOPMENT_ASSIGNED = "IA"
AWAITING_ANSWER = "AA"
WRITING = "W"
WRITING_FLEXIBLE = "WF"
AWAITING_APPROVAL_FOR_TESTSOLVING = "AT"
TESTSOLVING = "T"
AWAITING_TESTSOLVE_REVIEW = "TR"
REVISING = "R"
REVISING_POST_TESTSOLVING = "RP"
AWAITING_APPROVAL_POST_TESTSOLVING = "AO"
NEEDS_SOLUTION = "NS"
AWAITING_SOLUTION_APPROVAL = "AS"
NEEDS_POSTPROD = "NP"
ACTIVELY_POSTPRODDING = "PP"
POSTPROD_BLOCKED = "PB"
POSTPROD_BLOCKED_ON_TECH = "BT"
AWAITING_POSTPROD_APPROVAL = "AP"
NEEDS_FACTCHECK = "NF"
NEEDS_COPY_EDITS = "NC"
NEEDS_FINAL_REVISIONS = "NR"
NEEDS_HINTS = "NH"
AWAITING_HINTS_APPROVAL = "AH"
DONE = "D"
DEFERRED = "DF"
DEAD = "X"

# for ordering
# unclear if this was a good idea, but it does mean we can insert and reorder
# statuses without a database migration (?)
STATUSES = [
    INITIAL_IDEA,
    AWAITING_EDITOR,
    NEEDS_DISCUSSION,
    WAITING_FOR_ROUND,
    AWAITING_REVIEW,
    IDEA_IN_DEVELOPMENT,
    # IDEA_IN_DEVELOPMENT_ASSIGNED,
    AWAITING_ANSWER,
    WRITING,
    WRITING_FLEXIBLE,
    AWAITING_APPROVAL_FOR_TESTSOLVING,
    TESTSOLVING,
    AWAITING_TESTSOLVE_REVIEW,
    REVISING,
    REVISING_POST_TESTSOLVING,
    AWAITING_APPROVAL_POST_TESTSOLVING,
    NEEDS_SOLUTION,
    AWAITING_SOLUTION_APPROVAL,
    NEEDS_POSTPROD,
    ACTIVELY_POSTPRODDING,
    POSTPROD_BLOCKED,
    POSTPROD_BLOCKED_ON_TECH,
    AWAITING_POSTPROD_APPROVAL,
    NEEDS_FACTCHECK,
    NEEDS_FINAL_REVISIONS,
    NEEDS_COPY_EDITS,
    NEEDS_HINTS,
    AWAITING_HINTS_APPROVAL,
    DONE,
    DEFERRED,
    DEAD,
]


def get_status_rank(status):
    try:
        return STATUSES.index(status)
    except ValueError:  # not worth crashing imo
        return -1


def past_writing(status):
    return get_status_rank(status) > get_status_rank(
        WRITING_FLEXIBLE
    ) and get_status_rank(status) <= get_status_rank(DONE)


def past_testsolving(status):
    return get_status_rank(status) > get_status_rank(REVISING) and get_status_rank(
        status
    ) <= get_status_rank(DONE)


# Possible blockers:

EIC = "editor-in-chief"
EDITORS = "editor(s)"
AUTHORS = "the author(s)"
TESTSOLVERS = "testsolve coordinators"
POSTPRODDERS = "postprodders"
FACTCHECKERS = "factcheckers"
NOBODY = "nobody"

BLOCKERS_AND_TRANSITIONS = {
    INITIAL_IDEA: (
        AUTHORS,
        [
            (AWAITING_EDITOR, "✅ Ready for an editor"),
            (DEFERRED, "⏸️  Mark deferred"),
            (DEAD, "⏹️  Mark as dead"),
        ],
    ),
    AWAITING_EDITOR: (
        EIC,
        [
            (AWAITING_REVIEW, "✅ Editors assigned 👍 Answer confirmed"),
            (AWAITING_REVIEW, "✅ Editors assigned 🤷🏽‍♀️ No answer yet"),
            (NEEDS_DISCUSSION, "🗣 Need to discuss with EICs"),
            (INITIAL_IDEA, "🔄 Puzzle needs more work"),
        ]
    ),
    NEEDS_DISCUSSION: (
        EIC,
        [
            (AWAITING_REVIEW, "✅ Editors assigned 👍 Answer confirmed"),
            (AWAITING_REVIEW, "✅ Editors assigned 🤷🏽‍♀️ No answer yet"),
            (INITIAL_IDEA, "🔄 Send back to author(s)"),
        ]
    ),
    WAITING_FOR_ROUND: (
        EIC,
        [
            (AWAITING_REVIEW, "✅ Editors assigned 👍 Answer confirmed"),
            (AWAITING_REVIEW, "✅ Editors assigned 🤷🏽‍♀️ No answer yet"),
            (INITIAL_IDEA, "🔄 Send back to author(s)"),
        ]
    ),
    AWAITING_REVIEW: (
        EDITORS,
        [
            (IDEA_IN_DEVELOPMENT, "❌ Request revision"),
            # (IDEA_IN_DEVELOPMENT_ASSIGNED, "❌ Request revision with answer"),
            (AWAITING_ANSWER, "✅ Idea approved 🤷🏽‍♀️ need answer"),
            (WRITING, "✅ Idea approved 👍 Answer assigned"),
            (TESTSOLVING, "✏️ Ready to testsolve!"),
        ],
    ),
    IDEA_IN_DEVELOPMENT: (
        AUTHORS,
        [
            (AWAITING_REVIEW, "📝 Request review"),
            # (IDEA_IN_DEVELOPMENT_ASSIGNED, "✅ Mark as answer assigned"),
            (TESTSOLVING, "✏️ Ready to testsolve!"),
        ],
    ),
    # IDEA_IN_DEVELOPMENT_ASSIGNED: (
    #     AUTHORS,
    #     [
    #         (WRITING, "📝 Mark as writing"),
    #         (AWAITING_APPROVAL_FOR_TESTSOLVING, "📝 Request approval for testsolving"),
    #         (TESTSOLVING, "✅ Put into testsolving"),
    #     ],
    # ),
    AWAITING_ANSWER: (
        EIC,
        [
            (WRITING, "✅ Mark as answer assigned"),
        ]
    ),
    WRITING: (
        AUTHORS,
        [
            (AWAITING_ANSWER, "❌ Reject answer"),
            (AWAITING_APPROVAL_FOR_TESTSOLVING, "📝 Request approval for testsolving"),
        ],
    ),
    WRITING_FLEXIBLE: (
        AUTHORS,
        [
            (WRITING, "✅ Mark as answer assigned"),
            (AWAITING_APPROVAL_FOR_TESTSOLVING, "📝 Request approval for testsolving"),
        ],
    ),
    AWAITING_APPROVAL_FOR_TESTSOLVING: (
        EDITORS,
        [
            (TESTSOLVING, "✅ Puzzle is ready to be testsolved"),
            (REVISING, "❌ Request puzzle revision"),
        ],
    ),
    TESTSOLVING: (
        EDITORS,
        [
            (AWAITING_TESTSOLVE_REVIEW, "🧐 Testsolve done; author to review feedback"),
            (REVISING, "❌ Testsolve done; needs revision and more testsolving"),
            (REVISING_POST_TESTSOLVING, "⭕ Testsolve done; needs revision (but not testsolving)"),
        ],
    ),
    AWAITING_TESTSOLVE_REVIEW: (
        AUTHORS,
        [
            (TESTSOLVING, "🔄 Ready for more testsolving"),
            (REVISING, "❌ Needs revision (then more testsolving)"),
            (REVISING_POST_TESTSOLVING, "⭕ Needs revision (but can skip testsolving)"),
            (AWAITING_APPROVAL_POST_TESTSOLVING, "📝 Send to editors for approval"),
            (NEEDS_SOLUTION, "✅ Accept testsolve; request solution walkthru"),
            (NEEDS_POSTPROD, "⏩ Accept testsolve and solution; request postprod"),
        ],
    ),
    REVISING: (
        AUTHORS,
        [
            (AWAITING_APPROVAL_FOR_TESTSOLVING, "📝 Request approval for testsolving"),
            (TESTSOLVING, "⏩ Put into testsolving"),
            (AWAITING_APPROVAL_POST_TESTSOLVING, "⏭️  Request approval to skip testsolving" ),
        ],
    ),
    REVISING_POST_TESTSOLVING: (
        AUTHORS,
        [
            (AWAITING_APPROVAL_POST_TESTSOLVING, "📝 Request approval for post-testsolving"),
            (NEEDS_SOLUTION, "⏩ Mark revision as done"),
        ],
    ),
    AWAITING_APPROVAL_POST_TESTSOLVING: (
        EDITORS,
        [
            (REVISING_POST_TESTSOLVING, "❌ Request puzzle revision (done with testsolving)"),
            (TESTSOLVING, "🔙 Return to testsolving"),
            (NEEDS_SOLUTION, "✅ Accept revision; request solution"),
            (NEEDS_POSTPROD, "⏩ Accept revision and solution; request postprod"),
        ],
    ),
    NEEDS_SOLUTION: (
        AUTHORS,
        [
            (AWAITING_SOLUTION_APPROVAL, "📝 Request approval for solution"),
            (NEEDS_POSTPROD, "✅ Mark solution as finished; request postprod"),
        ],
    ),
    AWAITING_SOLUTION_APPROVAL: (
        EDITORS,
        [
            (NEEDS_SOLUTION, "❌ Request revisions to solution"),
            (NEEDS_POSTPROD, "✅ Mark solution as finished; request postprod"),
        ],
    ),
    NEEDS_POSTPROD: (
        POSTPRODDERS,
        [
            (ACTIVELY_POSTPRODDING, "🏠 Postprodding has started"),
            (AWAITING_POSTPROD_APPROVAL, "📝 Request approval after postprod"),
            (POSTPROD_BLOCKED, "❌✏️ Request revisions from author/art"),
            (POSTPROD_BLOCKED_ON_TECH, "❌💻 Blocked on tech request"),
        ],
    ),
    ACTIVELY_POSTPRODDING: (
        POSTPRODDERS,
        [
            (AWAITING_POSTPROD_APPROVAL, "📝 Request approval after postprod"),
            (NEEDS_FACTCHECK, "⏩ Mark postprod as finished; request factcheck"),
            (POSTPROD_BLOCKED, "❌✏️ Request revisions from author/art"),
            (POSTPROD_BLOCKED_ON_TECH, "❌💻 Blocked on tech request"),
        ],
    ),
    POSTPROD_BLOCKED: (
        AUTHORS,
        [
            (ACTIVELY_POSTPRODDING, "🏠 Postprodding can resume"),
            (NEEDS_POSTPROD, "📝 Mark as Ready for Postprod"),
            (POSTPROD_BLOCKED_ON_TECH, "❌💻 Blocked on tech request"),
            (AWAITING_POSTPROD_APPROVAL, "📝 Request approval after postprod"),
        ],
    ),
    POSTPROD_BLOCKED_ON_TECH: (
        POSTPRODDERS,
        [
            (ACTIVELY_POSTPRODDING, "🏠 Postprodding can resume"),
            (NEEDS_POSTPROD, "📝 Mark as Ready for Postprod"),
            (POSTPROD_BLOCKED, "❌✏️ Request revisions from author/art"),
            (AWAITING_POSTPROD_APPROVAL, "📝 Request approval after postprod"),
        ],
    ),
    AWAITING_POSTPROD_APPROVAL: (
        EDITORS,
        [
            (ACTIVELY_POSTPRODDING, "❌ Request revisions to postprod"),
            (NEEDS_FACTCHECK, "⏩ Mark postprod as finished; request factcheck"),
        ],
    ),
    NEEDS_FACTCHECK: (
        AUTHORS, #FACTCHECKERS,
        [
            (REVISING, "❌ Request large revisions (needs more testsolving)"),
            (REVISING_POST_TESTSOLVING, "❌ Request large revisions (doesn't need testsolving)"),
            (NEEDS_FINAL_REVISIONS, "🟡 Needs minor revisions"),
            (NEEDS_HINTS, "✅ Needs Hints"),
            (DONE, "⏩🎆 Mark as done! 🎆⏩"),
        ],
    ),
    NEEDS_FINAL_REVISIONS: (
        AUTHORS,
        [
            (NEEDS_FACTCHECK, "📝 Request factcheck (for large revisions)"),
            (NEEDS_COPY_EDITS, "✅ Request copy edits (for small revisions)"),
        ],
    ),
    NEEDS_COPY_EDITS: (
        FACTCHECKERS,
        [
            (NEEDS_HINTS, "✅ Needs Hints"),
            (DONE, "⏩🎆 Mark as done! 🎆⏩"),
        ]
    ),
    NEEDS_HINTS: (
        AUTHORS,
        [
            (AWAITING_HINTS_APPROVAL, "📝 Request approval for hints"),
            (DONE, "⏩🎆 Mark as done! 🎆⏩"),
        ],
    ),
    AWAITING_HINTS_APPROVAL: (
        EDITORS,
        [
            (NEEDS_HINTS, "❌ Request revisions to hints"), (DONE, "✅🎆 Mark as done! 🎆✅"),
            (DONE, "⏩🎆 Mark as done! 🎆⏩"),
        ],
    ),
    DEFERRED: (
        NOBODY,
        [
            (IDEA_IN_DEVELOPMENT, "✅ Back in development"),
        ]
    ),
}


def get_blocker(status):
    value = BLOCKERS_AND_TRANSITIONS.get(status)
    if value:
        return value[0]
    else:
        return NOBODY


def get_transitions(status, puzzle=None):
    value = BLOCKERS_AND_TRANSITIONS.get(status)
    if value:
        # add any transition logic here
        exclusions = []
        if puzzle:
            if puzzle.editors.all().exists():
                exclusions.append(AWAITING_EDITOR)

        return [s for s in value[1] if (not s[0] in exclusions)]
    else:
        return []


STATUSES_BLOCKED_ON_EDITORS = [
    status
    for status, (blocker, _) in BLOCKERS_AND_TRANSITIONS.items()
    if blocker == EDITORS
]
STATUSES_BLOCKED_ON_AUTHORS = [
    status
    for status, (blocker, _) in BLOCKERS_AND_TRANSITIONS.items()
    if blocker == AUTHORS
]

DESCRIPTIONS = {
    INITIAL_IDEA: "Initial Idea",
    AWAITING_EDITOR: "Awaiting Approval By EIC",
    NEEDS_DISCUSSION: "EICs are Discussing",
    WAITING_FOR_ROUND: "Waiting for Round to Open",
    AWAITING_REVIEW: "Awaiting Input By Editor",
    IDEA_IN_DEVELOPMENT: "Idea in Development",
    # IDEA_IN_DEVELOPMENT_ASSIGNED: "Idea in Development (Answer Assigned)",
    AWAITING_ANSWER: "Awaiting Answer",
    WRITING: "Writing (Answer Assigned)",
    WRITING_FLEXIBLE: "Writing (Answer Flexible)",
    AWAITING_APPROVAL_FOR_TESTSOLVING: "Awaiting Approval for Testsolving",
    TESTSOLVING: "Ready to be Testsolved",
    AWAITING_TESTSOLVE_REVIEW: "Awaiting Testsolve Review",
    REVISING: "Revising (Needs Testsolving)",
    REVISING_POST_TESTSOLVING: "Revising (Done with Testsolving)",
    AWAITING_APPROVAL_POST_TESTSOLVING: "Awaiting Approval (Done with Testsolving)",
    NEEDS_SOLUTION: "Needs Solution",
    AWAITING_SOLUTION_APPROVAL: "Awaiting Solution Approval",
    POSTPROD_BLOCKED: "Postproduction Blocked",
    POSTPROD_BLOCKED_ON_TECH: "Postproduction Blocked On Tech Request",
    NEEDS_POSTPROD: "Ready for Postprodding",
    ACTIVELY_POSTPRODDING: "Actively Postprodding",
    AWAITING_POSTPROD_APPROVAL: "Awaiting Approval After Postprod",
    NEEDS_FACTCHECK: "Needs Factcheck",
    NEEDS_FINAL_REVISIONS: "Needs Final Revisions",
    NEEDS_COPY_EDITS: "Needs Copy Edits",
    NEEDS_HINTS: "Needs Hints",
    AWAITING_HINTS_APPROVAL: "Awaiting Hints Approval",
    DONE: "Done",
    DEFERRED: "Deferred",
    DEAD: "Dead",
}


EMOJIS = {
    INITIAL_IDEA: "🥚",
    AWAITING_EDITOR: "🎩",
    NEEDS_DISCUSSION: "🗣",
    WAITING_FOR_ROUND: "⏳",
    AWAITING_ANSWER: "🤷🏽‍♀️",
    AWAITING_REVIEW: "👒",
    WRITING: "✏️",
    WRITING_FLEXIBLE: "✏️",
    AWAITING_APPROVAL_FOR_TESTSOLVING: "⏳✅",
    TESTSOLVING: "💡",
    REVISING: "✏️🔄",
    REVISING_POST_TESTSOLVING: "✏️🔄",
    NEEDS_POSTPROD: "🪵",
    ACTIVELY_POSTPRODDING: "🏠",
    POSTPROD_BLOCKED: "⚠️✏️",
    POSTPROD_BLOCKED_ON_TECH: "⚠️💻",
    AWAITING_POSTPROD_APPROVAL: "🧐",
    NEEDS_HINTS: "⁉",
    AWAITING_HINTS_APPROVAL: "🔍",
    NEEDS_COPY_EDITS: "📃",
    NEEDS_FACTCHECK: "📋",
    NEEDS_FINAL_REVISIONS: "🔬",
    DONE: "🏁",
    DEFERRED: "💤",
    DEAD: "💀",
}

TEMPLATES = {
    AWAITING_EDITOR: "awaiting_editor",
}

MAX_LENGTH = 2


def get_display(status):
    return DESCRIPTIONS.get(status, status)

def get_emoji(status):
    return EMOJIS.get(status, "")

def get_template(status):
    return TEMPLATES.get(status, 'status_update_email')


ALL_STATUSES = [
    {
        "value": status,
        "display": description,
        "emoji": get_emoji(status),
    }
    for status, description in DESCRIPTIONS.items()
]
