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
import androidx.compose.material.icons.automirrored.filled.Notes
import androidx.compose.material.icons.filled.Alarm
import androidx.compose.material.icons.filled.CheckCircle
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
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import app.reachy.companion.AppViewModel

private enum class Tab(val title: String) { Talk("Talk"), Todo("Reminders"), Notes("Notes"), Meetings("Meetings"), Alarms("Alarms") }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Shell(model: AppViewModel) {
    var tab by rememberSaveable { mutableStateOf(Tab.Talk) }
    var menu by remember { mutableStateOf(false) }
    var speak by remember { mutableStateOf(model.prefs.speakReplies) }
    val wide = isWide()
    var phoneAlarms by remember { mutableStateOf(model.prefs.phoneAlarms) }
    val context = LocalContext.current
    // The phone's backup alarm needs notifications to show its Stop button (Android 13+); ask once.
    val notifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    LaunchedEffect(Unit) {
        model.loadAlarms()   // schedules the phone's own alarm for each of the owner's alarms
        if (Build.VERSION.SDK_INT >= 33 && model.prefs.phoneAlarms && !model.prefs.askedAlarmNotifications &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) { model.prefs.askedAlarmNotifications = true; notifications.launch(Manifest.permission.POST_NOTIFICATIONS) }
    }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { model.loadChatHistory() }
    // Previous chats slide in from the left on a phone; when unfolded they are a permanent panel beside the chat (see below).
    ModalNavigationDrawer(
        drawerState = drawer, gesturesEnabled = tab == Tab.Talk && !wide,
        drawerContent = { ModalDrawerSheet { ChatHistoryPanel(model, onPicked = { scope.launch { drawer.close() } }) } },
    ) {
    Scaffold(
        topBar = {
            TopAppBar(title = { Text(tab.title) }, navigationIcon = {
                if (tab == Tab.Talk && !wide) IconButton({ scope.launch { drawer.open() } }) { Icon(Icons.Default.History, "Previous chats") }
            }, actions = {
                IconButton({ menu = true }) { Icon(Icons.Default.MoreVert, "Menu") }
                DropdownMenu(menu, { menu = false }) {
                    if (tab == Tab.Talk) DropdownMenuItem({ Text("New chat") }, { menu = false; model.newChat() })
                    DropdownMenuItem(
                        { Text(if (speak) "Read replies aloud: on" else "Read replies aloud: off") },
                        { speak = !speak; model.prefs.speakReplies = speak; menu = false },
                    )
                    DropdownMenuItem(
                        { Text(if (phoneAlarms) "Ring on this phone if Reachy can't: on" else "Ring on this phone if Reachy can't: off") },
                        { phoneAlarms = !phoneAlarms; model.prefs.phoneAlarms = phoneAlarms; model.loadAlarms(); menu = false },
                    )
                    DropdownMenuItem({ Text("Sign out") }, { menu = false; model.signOut() })
                }
            })
        },
        bottomBar = {
            if (!wide) NavigationBar {
                for (item in Tab.entries) NavigationBarItem(
                    selected = tab == item, onClick = { tab = item }, label = { Text(item.title) },
                    icon = { TabIcon(model, item) },
                )
            }
        },
    ) { padding ->
        val modifier = Modifier.padding(padding)
        Row(modifier) {
        if (wide) NavigationRail {
            for (item in Tab.entries) NavigationRailItem(
                selected = tab == item, onClick = { tab = item }, label = { Text(item.title) }, icon = { TabIcon(model, item) },
            )
        }
        Column(Modifier.weight(1f)) {
        RecordingBar(model)
        DeepReviewBanner()
        TailscaleBanner()
        when (tab) {
            Tab.Talk -> if (wide) TwoPane(Modifier.weight(1f), listWidth = 300, list = { ChatHistoryPanel(model) }, detail = { TalkScreen(model, speak, Modifier) })
                else TalkScreen(model, speak, Modifier.weight(1f))
            Tab.Todo -> RemindersScreen(model, Modifier.weight(1f))
            Tab.Notes -> NotesScreen(model, Modifier.weight(1f))
            Tab.Meetings -> MeetingsScreen(model, Modifier.weight(1f), onUseAsContext = { tab = Tab.Talk })
            Tab.Alarms -> AlarmsScreen(model, Modifier.weight(1f))
        }
        }
        }
    }
    }
}

@Composable
private fun TabIcon(model: AppViewModel, item: Tab) {
    BadgedBox(badge = { if (item == Tab.Meetings && model.recording) Badge(containerColor = androidx.compose.ui.graphics.Color(0xFFC62828)) }) {
        Icon(
            when (item) {
                Tab.Talk -> Icons.AutoMirrored.Filled.Chat
                Tab.Todo -> Icons.Default.CheckCircle
                Tab.Notes -> Icons.AutoMirrored.Filled.Notes
                Tab.Meetings -> Icons.Default.Mic
                Tab.Alarms -> Icons.Default.Alarm
            }, item.title,
        )
    }
}
