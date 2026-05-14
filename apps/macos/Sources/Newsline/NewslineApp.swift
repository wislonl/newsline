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
                Button("Fetch Now") { model.runPipeline() }
                    .keyboardShortcut("r", modifiers: .command)
                    .disabled(model.pipelineRunning)
                Button("Reload View") { model.reload() }
                    .keyboardShortcut("r", modifiers: [.command, .shift])
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

struct ChatMessage: Identifiable, Hashable {
    enum Role { case user, assistant, error }
    let id = UUID()
    let role: Role
    let text: String
}

@MainActor
final class AppModel: ObservableObject {
    private let store = Store()
    private(set) lazy var signals = Signals(dbURL: store.dbURL)
    private let chatService = ChatService()
    private let pipelineService = PipelineService()
    private var watcher: DBWatcher?
    @Published var stories: [StoryRow] = []
    @Published var selectedStoryID: String?
    @Published var events: [EventRow] = []
    @Published var dbExists: Bool = true
    @Published var currentThumb: Signals.Kind?

    /// In-memory chat history per story. Lost on quit (intentional for M4-1).
    @Published private(set) var chats: [String: [ChatMessage]] = [:]
    @Published private(set) var chatPending: Bool = false

    /// Manual pipeline refresh state (triggered by the toolbar button).
    @Published private(set) var pipelineRunning: Bool = false
    @Published private(set) var pipelineStatus: String = ""
    @Published private(set) var pipelineError: String?

    // Dwell tracking — when did the user select the current story?
    private var selectedAt: Date?

    init() {
        reload()
        watcher = DBWatcher(dbPath: store.dbURL.path) { [weak self] in
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

    // MARK: - pipeline (manual fetch)

    func runPipeline() {
        guard !pipelineRunning else { return }
        pipelineRunning = true
        pipelineError = nil
        pipelineStatus = "Starting…"

        Task { [pipelineService] in
            do {
                try await pipelineService.run { line in
                    // Already on main from PipelineService.
                    self.pipelineStatus = line
                }
                await MainActor.run {
                    self.pipelineStatus = "Done"
                    self.pipelineRunning = false
                    self.reload()
                }
            } catch {
                await MainActor.run {
                    self.pipelineError = error.localizedDescription
                    self.pipelineStatus = ""
                    self.pipelineRunning = false
                }
            }
        }
    }

    // MARK: - chat

    var currentMessages: [ChatMessage] {
        selectedStoryID.flatMap { chats[$0] } ?? []
    }

    func ask(_ question: String) {
        let trimmed = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let storyID = selectedStoryID else { return }
        chats[storyID, default: []].append(ChatMessage(role: .user, text: trimmed))
        chatPending = true

        Task { [chatService] in
            do {
                let answer = try await chatService.ask(storyID: storyID, question: trimmed)
                await MainActor.run {
                    // Only append to the right story — user may have switched.
                    self.chats[storyID, default: []].append(
                        ChatMessage(role: .assistant, text: answer))
                    if self.selectedStoryID == storyID { self.chatPending = false }
                }
            } catch {
                await MainActor.run {
                    self.chats[storyID, default: []].append(
                        ChatMessage(role: .error, text: error.localizedDescription))
                    if self.selectedStoryID == storyID { self.chatPending = false }
                }
            }
        }
    }
}
