package app.reachy.companion.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.automirrored.filled.LibraryBooks
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.Badge
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.rememberDrawerState
import androidx.compose.material.icons.filled.History
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.launch
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import app.reachy.companion.data.MEETING_DEEP_LINK
import app.reachy.companion.data.NavState
import app.reachy.companion.data.Primary
import app.reachy.companion.data.Section
import app.reachy.companion.data.decodeNav
import app.reachy.companion.data.encode
import app.reachy.companion.data.hasSecondary
import app.reachy.companion.data.sectionsOf
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.sp
import app.reachy.companion.AppViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Shell(model: AppViewModel) {
    var nav by rememberSaveable(stateSaver = androidx.compose.runtime.saveable.Saver<NavState, String>(save = { it.encode() }, restore = { decodeNav(it) })) { mutableStateOf(NavState()) }
    val section = nav.current
    val saveable = rememberSaveableStateHolder()  // each screen keeps its saved state (a selected page, a chosen tab) while another one is shown
    var menu by remember { mutableStateOf(false) }
    var speak by remember { mutableStateOf(model.prefs.speakReplies) }
    val wide = isWide()
    var phoneAlarms by remember { mutableStateOf(model.prefs.phoneAlarms) }
    var meetingReminders by remember { mutableStateOf(model.prefs.meetingReminders) }
    val context = LocalContext.current
    // A meeting reminder's "Start recording" lands on the Meetings tab, where the recorder waits for the owner's tap.
    LaunchedEffect(model.prepared) { if (model.prepared != null) nav = nav.open(MEETING_DEEP_LINK) }
    // The phone's backup alarm needs notifications to show its Stop button (Android 13+); ask once.
    val notifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    LaunchedEffect(Unit) {
        model.loadAlarms()   // schedules the phone's own alarm for each of the owner's alarms
        if (Build.VERSION.SDK_INT >= 33 && model.prefs.phoneAlarms && !model.prefs.askedAlarmNotifications &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) { model.prefs.askedAlarmNotifications = true; notifications.launch(Manifest.permission.POST_NOTIFICATIONS) }
        else if (Build.VERSION.SDK_INT >= 33 && model.prefs.meetingReminders && !model.prefs.askedReminderNotifications &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) { model.prefs.askedReminderNotifications = true; notifications.launch(Manifest.permission.POST_NOTIFICATIONS) }
    }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { model.loadChatHistory() }
    // Previous chats slide in from the left on a phone; when unfolded they are a permanent panel beside the chat (see below).
    ModalNavigationDrawer(
        drawerState = drawer, gesturesEnabled = nav.primary == Primary.Talk && !wide,
        drawerContent = { ModalDrawerSheet { ChatHistoryPanel(model, onPicked = { scope.launch { drawer.close() } }) } },
    ) {
    Scaffold(
        topBar = {
            TopAppBar(title = { Text(section.title) }, navigationIcon = {
                if (nav.primary == Primary.Talk && !wide) IconButton({ scope.launch { drawer.open() } }) { Icon(Icons.Default.History, "Previous chats") }
            }, actions = {
                IconButton({ menu = true }) { Icon(Icons.Default.MoreVert, "Menu") }
                DropdownMenu(menu, { menu = false }) {
                    if (nav.primary == Primary.Talk) DropdownMenuItem({ Text("New chat") }, { menu = false; model.newChat() })
                    DropdownMenuItem(
                        { Text(if (speak) "Read replies aloud: on" else "Read replies aloud: off") },
                        { speak = !speak; model.prefs.speakReplies = speak; menu = false },
                    )
                    DropdownMenuItem(
                        { Text(if (phoneAlarms) "Ring on this phone if Reachy can't: on" else "Ring on this phone if Reachy can't: off") },
                        { phoneAlarms = !phoneAlarms; model.prefs.phoneAlarms = phoneAlarms; model.loadAlarms(); menu = false },
                    )
                    DropdownMenuItem(
                        { Text(if (meetingReminders) "Meeting reminders: on" else "Meeting reminders: off") },
                        {
                            meetingReminders = !meetingReminders; model.setMeetingReminders(meetingReminders); menu = false
                            if (meetingReminders && Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                                model.prefs.askedReminderNotifications = true; notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                            }
                        },
                    )
                    DropdownMenuItem({ Text("Sign out") }, { menu = false; model.signOut() })
                }
            })
        },
        bottomBar = {
            if (!wide) NavigationBar {
                for (item in Primary.entries) NavigationBarItem(
                    selected = nav.primary == item, onClick = { nav = nav.selectPrimary(item) }, label = { Text(item.title, maxLines = 1) },
                    icon = { PrimaryIcon(model, item) },
                )
            }
        },
    ) { padding ->
        val modifier = Modifier.padding(padding)
        Row(modifier) {
        if (wide) NavigationRail {
            for (item in Primary.entries) NavigationRailItem(
                selected = nav.primary == item, onClick = { nav = nav.selectPrimary(item) }, label = { Text(item.title) }, icon = { PrimaryIcon(model, item) },
            )
        }
        Column(Modifier.weight(1f)) {
        RecordingBar(model)
        DeepReviewBanner()
        TailscaleBanner()
        if (hasSecondary(nav.primary)) SecondaryNav(nav.primary, section) { nav = nav.open(it) }
        saveable.SaveableStateProvider(section.name) {
            when (section) {
                Section.Talk -> if (wide) TwoPane(Modifier.weight(1f), listWidth = 300, list = { ChatHistoryPanel(model) }, detail = { TalkScreen(model, speak, Modifier) })
                    else TalkScreen(model, speak, Modifier.weight(1f))
                Section.Reminders -> RemindersScreen(model, Modifier.weight(1f))
                Section.Notes -> NotesScreen(model, Modifier.weight(1f))
                Section.Meetings -> MeetingsScreen(model, Modifier.weight(1f), onUseAsContext = { nav = nav.open(Section.Talk) })
                Section.Calendar -> CalendarScreen(model, Modifier.weight(1f))
                Section.Documents -> DocumentsScreen(model, Modifier.weight(1f))
                Section.Alarms -> AlarmsScreen(model, Modifier.weight(1f))
            }
        }
        }
        }
    }
    }
}

/** The labelled screens inside a group (Planner: Calendar, Reminders, Alarms; Library: Notes, Documents). Text tabs, so every destination has a visible name and a tab role. */
@Composable
private fun SecondaryNav(primary: Primary, current: Section, onSelect: (Section) -> Unit) {
    val sections = sectionsOf(primary)
    TabRow(selectedTabIndex = sections.indexOf(current).coerceAtLeast(0), modifier = Modifier.semantics { contentDescription = "${primary.title} sections" }) {
        for (item in sections) Tab(selected = item == current, onClick = { onSelect(item) }, text = { Text(item.title, maxLines = 1) })
    }
}

@Composable
private fun PrimaryIcon(model: AppViewModel, item: Primary) {
    BadgedBox(badge = { if (item == Primary.Meetings && model.recording) Badge(containerColor = androidx.compose.ui.graphics.Color(0xFFC62828)) }) {
        Icon(
            when (item) {
                Primary.Talk -> Icons.AutoMirrored.Filled.Chat
                Primary.Planner -> Icons.Default.CalendarMonth
                Primary.Meetings -> Icons.Default.Mic
                Primary.Library -> Icons.AutoMirrored.Filled.LibraryBooks
            }, item.title,
        )
    }
}
