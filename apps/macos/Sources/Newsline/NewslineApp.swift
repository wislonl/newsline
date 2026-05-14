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
                Button(L10n.fetchNow) { model.runPipeline() }
                    .keyboardShortcut("r", modifiers: .command)
                    .disabled(model.pipelineRunning)
                Button(L10n.reloadView) { model.reload() }
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
        model?.sidecar.shutdown()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

struct ChatMessage: Identifiable, Hashable {
    enum Role { case user, assistant, error }
    let id: UUID
    let role: Role
    let text: String

    init(role: Role, text: String, idOverride: UUID? = nil) {
        self.id = idOverride ?? UUID()
        self.role = role
        self.text = text
    }
}

@MainActor
final class AppModel: ObservableObject {
    private let store = Store()
    private(set) lazy var signals = Signals(dbURL: store.dbURL)
    private let chatService = ChatService()
    private let pipelineService = PipelineService()
    private(set) lazy var chatStore = ChatStore(dbURL: store.dbURL)
    let sidecar = Sidecar()
    private var watcher: DBWatcher?
    private var statusClearTask: Task<Void, Never>?

    /// Last story dismissed, retained briefly so the user can hit "撤销".
    struct DismissUndo: Equatable {
        let storyID: String
        let leadItemID: String
        let title: String
    }
    @Published var pendingUndo: DismissUndo?
    private var undoExpireTask: Task<Void, Never>?
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

    /// Sidebar filter: show only stories whose top event scored ≥ this.
    /// Persisted in UserDefaults so it survives relaunches.
    @Published var minScore: Double {
        didSet { UserDefaults.standard.set(minScore, forKey: "newsline.minScore") }
    }
    @Published var showRead: Bool {
        didSet { UserDefaults.standard.set(showRead, forKey: "newsline.showRead") }
    }
    @Published var searchQuery: String = ""
    @Published var activeTag: String? = nil

    var filteredStories: [StoryRow] {
        let q = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let tag = activeTag
        return stories.filter { s in
            guard (s.topScore ?? 0) >= minScore else { return false }
            if s.isDismissed { return false }
            if !showRead && s.isRead { return false }
            if let tag, !s.leadTags.contains(where: { $0.caseInsensitiveCompare(tag) == .orderedSame }) {
                return false
            }
            if !q.isEmpty {
                let hay = (s.title + " " + (s.summary ?? "")).lowercased()
                if !hay.contains(q) { return false }
            }
            return true
        }
    }

    /// Bucketed by date for sectioned sidebar display.
    struct Section: Identifiable {
        let id: String
        let title: String
        let stories: [StoryRow]
    }

    var groupedStories: [Section] {
        let cal = Calendar.current
        let now = Date()
        let startOfToday = cal.startOfDay(for: now)
        let startOfYesterday = cal.date(byAdding: .day, value: -1, to: startOfToday)!
        let weekAgo = cal.date(byAdding: .day, value: -7, to: startOfToday)!

        var todayList: [StoryRow] = []
        var yesterdayList: [StoryRow] = []
        var thisWeekList: [StoryRow] = []
        var olderList: [StoryRow] = []

        for s in filteredStories {
            guard let d = Self.parseISO(s.lastUpdated) else {
                olderList.append(s); continue
            }
            if d >= startOfToday { todayList.append(s) }
            else if d >= startOfYesterday { yesterdayList.append(s) }
            else if d >= weekAgo { thisWeekList.append(s) }
            else { olderList.append(s) }
        }

        var sections: [Section] = []
        if !todayList.isEmpty { sections.append(.init(id: "today", title: L10n.sectionToday, stories: todayList)) }
        if !yesterdayList.isEmpty { sections.append(.init(id: "y", title: L10n.sectionYesterday, stories: yesterdayList)) }
        if !thisWeekList.isEmpty { sections.append(.init(id: "w", title: L10n.sectionThisWeek, stories: thisWeekList)) }
        if !olderList.isEmpty { sections.append(.init(id: "o", title: L10n.sectionOlder, stories: olderList)) }
        return sections
    }

    private static let iso1 = ISO8601DateFormatter()
    private static let iso2: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    static func parseISO(_ s: String) -> Date? {
        iso2.date(from: s) ?? iso1.date(from: s)
    }

    // Dwell tracking — when did the user select the current story?
    private var selectedAt: Date?

    init() {
        let stored = UserDefaults.standard.object(forKey: "newsline.minScore") as? Double
        self.minScore = stored ?? 8.0
        let storedShowRead = UserDefaults.standard.object(forKey: "newsline.showRead") as? Bool
        self.showRead = storedShowRead ?? false
        reload()
        watcher = DBWatcher(dbPath: store.dbURL.path) { [weak self] in
            self?.reload()
        }
        watcher?.start()

        // Auto-select first visible story so j/k/space work immediately.
        if selectedStoryID == nil, let first = groupedStories.first?.stories.first {
            select(first.id)
        }

        // Pre-warm the chat sidecar in the background so the first user
        // question doesn't pay the 1-2s health-check wait.
        Task { [sidecar] in _ = try? await sidecar.ensureRunning() }
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

        // Lazy-load persisted chat for this story (once per session).
        if let id, chats[id] == nil {
            chats[id] = chatStore.load(storyID: id)
        }

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

    // MARK: - keyboard navigation

    /// Flattened ordering of currently visible stories across sections.
    private var visibleOrder: [String] {
        groupedStories.flatMap { $0.stories.map(\.id) }
    }

    func selectNext() {
        let order = visibleOrder
        guard !order.isEmpty else { return }
        if let current = selectedStoryID, let idx = order.firstIndex(of: current) {
            let next = order[min(idx + 1, order.count - 1)]
            select(next)
        } else {
            select(order.first)
        }
    }

    func selectPrevious() {
        let order = visibleOrder
        guard !order.isEmpty else { return }
        if let current = selectedStoryID, let idx = order.firstIndex(of: current) {
            let prev = order[max(idx - 1, 0)]
            select(prev)
        } else {
            select(order.last)
        }
    }

    /// Open the lead event URL in the default browser.
    func openLeadInBrowser() {
        guard let first = events.first, let url = URL(string: first.url) else { return }
        NSWorkspace.shared.open(url)
    }

    /// Mark the current story dismissed: record signal + remove from sidebar.
    /// Selecting another story shows fresh content immediately. The
    /// dismiss is held as `pendingUndo` for 8 seconds so accidental
    /// clicks can be reversed without diving into SQL.
    func dismissCurrent() {
        guard let storyID = selectedStoryID,
              let story = stories.first(where: { $0.id == storyID }) else { return }
        signals.record(itemID: story.leadItemID, kind: .dismiss)
        pendingUndo = DismissUndo(
            storyID: story.id, leadItemID: story.leadItemID, title: story.title)
        stories.removeAll { $0.id == storyID }
        select(nil)
        scheduleUndoExpire()
    }

    func undoDismiss() {
        guard let u = pendingUndo else { return }
        signals.delete(itemID: u.leadItemID, kind: .dismiss)
        pendingUndo = nil
        undoExpireTask?.cancel()
        // Re-read DB so the story comes back into the list.
        reload()
        select(u.storyID)
    }

    private func scheduleUndoExpire() {
        undoExpireTask?.cancel()
        undoExpireTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            if !Task.isCancelled { self.pendingUndo = nil }
        }
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

    private func scheduleStatusClear() {
        statusClearTask?.cancel()
        statusClearTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            if !Task.isCancelled { self.pipelineStatus = "" }
        }
    }

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
                    self.scheduleStatusClear()
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
        // Build history from finalized prior turns BEFORE appending this question.
        let history: [[String: String]] = (chats[storyID] ?? []).compactMap { msg in
            guard !msg.text.isEmpty else { return nil }
            switch msg.role {
            case .user:      return ["role": "user",      "content": msg.text]
            case .assistant: return ["role": "assistant", "content": msg.text]
            case .error:     return nil  // errors aren't part of the conversation
            }
        }
        chats[storyID, default: []].append(ChatMessage(role: .user, text: trimmed))
        chatStore.append(storyID: storyID, role: .user, text: trimmed)
        // Append a draft assistant message we'll fill in as chunks arrive.
        let draft = ChatMessage(role: .assistant, text: "")
        chats[storyID, default: []].append(draft)
        let draftID = draft.id
        chatPending = true

        Task { [chatService, sidecar, chatStore] in
            do {
                let base = try await sidecar.ensureRunning()
                let stream = chatService.askStream(
                    storyID: storyID, question: trimmed,
                    history: history, baseURL: base)
                var accumulated = ""
                for try await chunk in stream {
                    accumulated += chunk
                    let snapshot = accumulated
                    await MainActor.run {
                        self.replaceDraft(storyID: storyID, id: draftID, text: snapshot)
                    }
                }
                let finalText = accumulated
                await MainActor.run {
                    if !finalText.isEmpty {
                        chatStore.append(storyID: storyID, role: .assistant, text: finalText)
                    }
                    if self.selectedStoryID == storyID { self.chatPending = false }
                }
            } catch {
                await MainActor.run {
                    self.replaceDraft(storyID: storyID, id: draftID,
                                      text: error.localizedDescription, role: .error)
                    if self.selectedStoryID == storyID { self.chatPending = false }
                }
            }
        }
    }

    private func replaceDraft(storyID: String, id: UUID, text: String,
                              role: ChatMessage.Role = .assistant) {
        guard var msgs = chats[storyID] else { return }
        if let idx = msgs.firstIndex(where: { $0.id == id }) {
            msgs[idx] = ChatMessage(role: role, text: text, idOverride: id)
            chats[storyID] = msgs
        }
    }
}
