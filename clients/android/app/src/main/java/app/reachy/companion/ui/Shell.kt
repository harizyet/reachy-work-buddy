package app.reachy.companion.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Chat
import androidx.compose.material.icons.automirrored.filled.Notes
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
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

private enum class Tab(val title: String) { Talk("Talk"), Todo("To-do"), Notes("Notes"), Meetings("Meetings") }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Shell(model: AppViewModel) {
    var tab by rememberSaveable { mutableStateOf(Tab.Talk) }
    var menu by remember { mutableStateOf(false) }
    var speak by remember { mutableStateOf(model.prefs.speakReplies) }
    Scaffold(
        topBar = {
            TopAppBar(title = { Text(tab.title) }, actions = {
                IconButton({ menu = true }) { Icon(Icons.Default.MoreVert, "Menu") }
                DropdownMenu(menu, { menu = false }) {
                    if (tab == Tab.Talk) DropdownMenuItem({ Text("New chat") }, { menu = false; model.newChat() })
                    DropdownMenuItem(
                        { Text(if (speak) "Read replies aloud: on" else "Read replies aloud: off") },
                        { speak = !speak; model.prefs.speakReplies = speak; menu = false },
                    )
                    DropdownMenuItem({ Text("Sign out") }, { menu = false; model.signOut() })
                }
            })
        },
        bottomBar = {
            NavigationBar {
                for (item in Tab.entries) NavigationBarItem(
                    selected = tab == item, onClick = { tab = item }, label = { Text(item.title) },
                    icon = {
                        BadgedBox(badge = { if (item == Tab.Meetings && model.recording) Badge(containerColor = androidx.compose.ui.graphics.Color(0xFFC62828)) }) {
                            Icon(
                                when (item) {
                                    Tab.Talk -> Icons.AutoMirrored.Filled.Chat
                                    Tab.Todo -> Icons.Default.CheckCircle
                                    Tab.Notes -> Icons.AutoMirrored.Filled.Notes
                                    Tab.Meetings -> Icons.Default.Mic
                                }, item.title,
                            )
                        }
                    },
                )
            }
        },
    ) { padding ->
        val modifier = Modifier.padding(padding)
        Column(modifier) {
        RecordingBar(model)
        DeepReviewBanner()
        TailscaleBanner()
        when (tab) {
            Tab.Talk -> TalkScreen(model, speak, Modifier.weight(1f))
            Tab.Todo -> TasksScreen(model, Modifier.weight(1f))
            Tab.Notes -> NotesScreen(model, Modifier.weight(1f))
            Tab.Meetings -> MeetingsScreen(model, Modifier.weight(1f), onUseAsContext = { tab = Tab.Talk })
        }
        }
    }
}
