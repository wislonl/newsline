import SwiftUI
import AppKit

@main
struct NewslineApp: App {
    @StateObject private var model = AppModel()
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        WindowGroup("Newsline") {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 900, minHeight: 560)
        }
        .windowStyle(.titleBar)
        .commands {
            CommandGroup(after: .newItem) {
                Button("Refresh") { model.reload() }
                    .keyboardShortcut("r", modifiers: .command)
            }
        }
    }
}

/// SwiftPM-built apps don't register with LaunchServices, so without this the
/// window stays hidden behind the launching terminal. Force regular activation
/// and bring the window to the front.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

@MainActor
final class AppModel: ObservableObject {
    private let store = Store()
    private var watcher: DBWatcher?
    @Published var stories: [StoryRow] = []
    @Published var selectedStoryID: String?
    @Published var events: [EventRow] = []
    @Published var dbExists: Bool = true

    init() {
        reload()
        watcher = DBWatcher(path: store.dbURL.path) { [weak self] in
            self?.reload()
        }
        watcher?.start()
    }

    deinit {
        watcher?.stop()
    }

    func reload() {
        dbExists = store.storyExists()
        stories = store.activeStories(limit: 200)
        if let id = selectedStoryID {
            events = store.events(storyID: id)
        } else {
            events = []
        }
    }

    func select(_ id: String?) {
        selectedStoryID = id
        events = id.map(store.events(storyID:)) ?? []
    }
}
