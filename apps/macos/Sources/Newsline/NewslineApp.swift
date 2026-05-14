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
                .onAppear { delegate.model = model }
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
    weak var model: AppModel?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationDidResignActive(_ notification: Notification) {
        model?.flushDwell()
    }

    func applicationWillTerminate(_ notification: Notification) {
        model?.flushDwell()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

@MainActor
final class AppModel: ObservableObject {
    private let store = Store()
    private(set) lazy var signals = Signals(dbURL: store.dbURL)
    private var watcher: DBWatcher?
    @Published var stories: [StoryRow] = []
    @Published var selectedStoryID: String?
    @Published var events: [EventRow] = []
    @Published var dbExists: Bool = true
    @Published var currentThumb: Signals.Kind?

    // Dwell tracking — when did the user select the current story?
    private var selectedAt: Date?

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
        // Close out previous selection's dwell first.
        flushDwell()

        selectedStoryID = id
        events = id.map(store.events(storyID:)) ?? []

        // Record open for the representative (first) event.
        if let first = events.first {
            signals.record(itemID: first.id, kind: .open)
            currentThumb = signals.currentThumb(itemID: first.id)
            selectedAt = Date()
        } else {
            currentThumb = nil
            selectedAt = nil
        }
    }

    func thumbUp() {
        guard let id = currentEventID else { return }
        signals.record(itemID: id, kind: .thumbUp)
        currentThumb = .thumbUp
    }

    func thumbDown() {
        guard let id = currentEventID else { return }
        signals.record(itemID: id, kind: .thumbDown)
        currentThumb = .thumbDown
    }

    /// Called when the window/app loses focus or quits — flush any open dwell.
    func flushDwell() {
        guard let id = currentEventID, let start = selectedAt else { return }
        let ms = Date().timeIntervalSince(start) * 1000.0
        // Ignore trivial dwells (<1s); they're scrolling-by, not reading.
        if ms >= 1000 {
            signals.record(itemID: id, kind: .dwellMs, value: ms)
        }
        selectedAt = nil
    }

    private var currentEventID: String? { events.first?.id }
}
