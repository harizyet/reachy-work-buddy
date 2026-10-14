package app.reachy.companion.data

/*
 * The app's navigation hierarchy: five primary destinations, two of which group secondary screens. Pure, so the structure (what lives where, where a deep link lands, what is
 * restored when the owner comes back to a group) is tested on the JVM; the composables only draw it.
 */

enum class Primary(val title: String) { Home("Home"), Talk("Talk"), Planner("Planner"), Meetings("Meetings"), Library("Library") }

enum class Section(val primary: Primary, val title: String) {
    Home(Primary.Home, "Home"),
    Talk(Primary.Talk, "Talk"),
    Calendar(Primary.Planner, "Calendar"),
    Reminders(Primary.Planner, "Reminders"),
    Alarms(Primary.Planner, "Alarms"),
    Meetings(Primary.Meetings, "Meetings"),
    Notes(Primary.Library, "Notes"),
    Documents(Primary.Library, "Documents"),
}

/** The screens a primary destination holds, in the order of its secondary navigation. A group with one screen has no secondary navigation. */
fun sectionsOf(primary: Primary): List<Section> = Section.entries.filter { it.primary == primary }

fun hasSecondary(primary: Primary): Boolean = sectionsOf(primary).size > 1

/**
 * Where the owner is: the primary destination, and the last screen chosen inside each group, so leaving Planner for Meetings and coming back lands on the screen that was
 * open, not the first. Immutable; every move returns a new state.
 */
data class NavState(val primary: Primary = Primary.Home, val planner: Section = Section.Calendar, val library: Section = Section.Notes) {
    val current: Section
        get() = when (primary) {
            Primary.Home -> Section.Home
            Primary.Talk -> Section.Talk
            Primary.Planner -> planner
            Primary.Meetings -> Section.Meetings
            Primary.Library -> library
        }

    fun selectPrimary(target: Primary) = copy(primary = target)

    /** Opens a screen directly (a deep link, "use as context"), remembering it as its group's last screen. */
    fun open(section: Section): NavState = when (section.primary) {
        Primary.Planner -> copy(primary = Primary.Planner, planner = section)
        Primary.Library -> copy(primary = Primary.Library, library = section)
        else -> copy(primary = section.primary)
    }
}

/** Encodes a state for rememberSaveable (rotation, folding and process restarts keep the position). */
fun NavState.encode(): String = "${primary.name},${planner.name},${library.name}"

fun decodeNav(text: String?): NavState {
    val parts = text?.split(",") ?: return NavState()
    return runCatching {
        NavState(Primary.valueOf(parts[0]), Section.valueOf(parts[1]).takeIf { it.primary == Primary.Planner } ?: Section.Calendar, Section.valueOf(parts[2]).takeIf { it.primary == Primary.Library } ?: Section.Notes)
    }.getOrDefault(NavState())
}

/** Where a meeting reminder's "Start recording" and the recorder notifications land: the Meetings screen, which holds recording, history and analysis. */
val MEETING_DEEP_LINK: Section = Section.Meetings
