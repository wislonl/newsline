import SwiftUI

private let isoParser: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f
}()

private let isoParserNoFraction: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime]
    return f
}()

/// Parse the timestamps written by the Python daemon (datetime.isoformat()).
/// They look like `2026-05-14T00:19:33.123456+00:00` or without fraction.
private func parseTimestamp(_ s: String?) -> Date? {
    guard let s, !s.isEmpty else { return nil }
    return isoParser.date(from: s) ?? isoParserNoFraction.date(from: s)
}

private func displayDate(_ s: String?) -> String {
    parseTimestamp(s).map { $0.newslineDetailFormat } ?? (s ?? "")
}

private func sidebarDate(_ s: String?) -> String {
    parseTimestamp(s).map { $0.newslineSidebarFormat }
        ?? (s?.prefix(10).description ?? "")
}

struct ContentView: View {
    @EnvironmentObject var model: AppModel
    @FocusState private var searchFocused: Bool

    var body: some View {
        NavigationSplitView {
            storyList
        } detail: {
            storyDetail
        }
        .navigationTitle(L10n.windowTitle)
        .background(keyboardCommands)  // invisible buttons for j/k/space/Enter/Cmd+F
        .overlay(alignment: .bottom) {
            if let u = model.pendingUndo {
                UndoBanner(undo: u, onUndo: model.undoDismiss)
                    .padding(20)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: model.pendingUndo)
        .toolbar {
            ToolbarItem(placement: .status) {
                pipelineStatusView
            }
            ToolbarItem(placement: .primaryAction) {
                Button(action: model.runPipeline) {
                    if model.pipelineRunning {
                        ProgressView().controlSize(.small)
                    } else {
                        Label(L10n.fetchLabel, systemImage: "arrow.clockwise")
                    }
                }
                .help(L10n.fetchTooltip)
                .disabled(model.pipelineRunning)
            }
        }
    }

    // MARK: - Hidden keyboard shortcuts
    // Single-key shortcuts (no modifier) only fire when no TextField has
    // focus — exactly the behavior we want for j/k/space/Enter.

    @ViewBuilder
    private var keyboardCommands: some View {
        HStack(spacing: 0) {
            Button("") { model.selectNext() }
                .keyboardShortcut(KeyEquivalent("j"), modifiers: [])
            Button("") { model.selectPrevious() }
                .keyboardShortcut(KeyEquivalent("k"), modifiers: [])
            Button("") {
                // Space: move to the next story (open implies read; advance).
                model.selectNext()
            }
            .keyboardShortcut(.space, modifiers: [])
            Button("") { model.openLeadInBrowser() }
                .keyboardShortcut(.return, modifiers: [])
            Button("") { searchFocused = true }
                .keyboardShortcut("f", modifiers: .command)
        }
        .frame(width: 0, height: 0)
        .opacity(0)
    }

    // MARK: - Toolbar status

    @ViewBuilder
    private var pipelineStatusView: some View {
        if let err = model.pipelineError {
            Label(err, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
                .lineLimit(1)
                .help(err)
        } else if model.pipelineRunning || !model.pipelineStatus.isEmpty {
            Text(model.pipelineStatus)
                .font(.caption).foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }

    // MARK: - Sidebar: stories

    @ViewBuilder
    private var storyList: some View {
        if !model.dbExists {
            VStack(spacing: 8) {
                Text(L10n.noDatabaseTitle).font(.headline)
                Text(L10n.noDatabaseHint)
                    .font(.callout).foregroundStyle(.secondary)
            }
            .padding()
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if model.stories.isEmpty {
            ContentUnavailableView(L10n.noStoriesTitle,
                                   systemImage: "newspaper",
                                   description: Text(L10n.noStoriesHint))
        } else {
            VStack(spacing: 0) {
                searchBar
                if let tag = model.activeTag {
                    activeTagBar(tag: tag)
                }
                Divider()
                scoreFilterBar
                Divider()
                let sections = model.groupedStories
                if sections.isEmpty {
                    ContentUnavailableView(
                        L10n.isChinese ? "没有 ≥\(Int(model.minScore)) 分的故事" : "Nothing ≥ \(Int(model.minScore))",
                        systemImage: "line.3.horizontal.decrease.circle",
                        description: Text(L10n.isChinese ? "拖动滑块降低阈值，或勾选显示已读。" : "Lower the threshold, or enable Show Read.")
                    )
                    .frame(maxHeight: .infinity)
                } else {
                    List(selection: Binding(
                        get: { model.selectedStoryID },
                        set: { model.select($0) }
                    )) {
                        ForEach(sections) { section in
                            Section(header: Text(section.title)) {
                                ForEach(section.stories) { story in
                                    StoryRowItem(story: story).tag(story.id)
                                }
                            }
                        }
                    }
                    .listStyle(.sidebar)
                }
            }
        }
    }

    @ViewBuilder
    private var searchBar: some View {
        HStack(spacing: 6) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(.secondary)
            TextField(L10n.searchPlaceholder, text: $model.searchQuery)
                .textFieldStyle(.plain)
                .focused($searchFocused)
            if !model.searchQuery.isEmpty {
                Button(action: { model.searchQuery = "" }) {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
    }

    @ViewBuilder
    private func activeTagBar(tag: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: "tag.fill").foregroundStyle(.tint)
            Text(L10n.filteringByTag(tag))
                .font(.caption).bold()
            Spacer()
            Button(action: { model.activeTag = nil }) {
                Image(systemName: "xmark.circle.fill").foregroundStyle(.tertiary)
            }
            .buttonStyle(.plain)
            .help(L10n.clearTagFilter)
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(.tint.opacity(0.08))
    }

    @ViewBuilder
    private var scoreFilterBar: some View {
        let visibleCount = model.groupedStories.reduce(0) { $0 + $1.stories.count }
        let total = model.stories.count
        VStack(spacing: 4) {
            HStack(spacing: 8) {
                Image(systemName: "star.fill").foregroundStyle(.yellow)
                Text("≥ \(String(format: "%.0f", model.minScore))")
                    .font(.callout).bold().monospacedDigit()
                Slider(value: $model.minScore, in: 0...10, step: 1)
                    .controlSize(.mini)
                Text("\(visibleCount)/\(total)")
                    .font(.caption).foregroundStyle(.secondary).monospacedDigit()
            }
            Toggle(L10n.showRead, isOn: $model.showRead)
                .toggleStyle(.checkbox)
                .controlSize(.small)
                .font(.caption)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
    }

    // MARK: - Detail: events of selected story

    @ViewBuilder
    private var storyDetail: some View {
        if let id = model.selectedStoryID,
           let story = model.stories.first(where: { $0.id == id }) {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text(story.title)
                        .font(.title2).bold()
                    HStack(spacing: 12) {
                        Label(L10n.eventCount(story.eventCount), systemImage: "circle.dotted")
                        if let s = story.topScore {
                            Label(L10n.topScore(s), systemImage: "star")
                        }
                        Text(displayDate(story.lastUpdated))
                            .foregroundStyle(.secondary)
                        Spacer()
                        ThumbButton(kind: .thumbUp,
                                    current: model.currentThumb,
                                    action: model.thumbUp)
                        ThumbButton(kind: .thumbDown,
                                    current: model.currentThumb,
                                    action: model.thumbDown)
                        Button(action: model.dismissCurrent) {
                            Image(systemName: "eye.slash")
                        }
                        .buttonStyle(.plain)
                        .help(L10n.dismissHelp)
                        if let first = model.events.first,
                           let url = URL(string: first.url) {
                            Link(destination: url) {
                                Label(L10n.openLink, systemImage: "arrow.up.right.square")
                            }
                        }
                    }
                    .font(.callout).foregroundStyle(.secondary)

                    if let summary = story.summary, !summary.isEmpty {
                        Text(summary).font(.body)
                    }

                    if !story.leadTags.isEmpty {
                        FlowChips(tags: story.leadTags) { tag in
                            model.activeTag = tag
                        }
                    }

                    if let reason = story.leadReason, !reason.isEmpty {
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: "info.circle")
                                .foregroundStyle(.tertiary)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(L10n.aiReasonLabel)
                                    .font(.caption).foregroundStyle(.secondary)
                                Text(reason).font(.callout).foregroundStyle(.secondary)
                            }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 6))
                    }

                    // For multi-event stories show the timeline. Single-event
                    // stories already showed everything above; no need to repeat.
                    if model.events.count > 1 {
                        Divider().padding(.vertical, 8)
                        Text(L10n.timelineHeader).font(.headline)
                        ForEach(model.events) { e in
                            EventCard(event: e)
                        }
                    }

                    Divider().padding(.vertical, 8)
                    ChatPanel()
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            ContentUnavailableView(L10n.selectStoryTitle,
                                   systemImage: "sidebar.left",
                                   description: Text(L10n.selectStoryHint))
        }
    }
}

private struct StoryRowItem: View {
    let story: StoryRow
    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            SourceBadge(source: story.leadSource)
                .padding(.top, 3)
            VStack(alignment: .leading, spacing: 4) {
                Text(story.title)
                    .lineLimit(2)
                    .font(.callout)
                    .foregroundStyle(story.isRead ? Color.secondary : Color.primary)
                HStack(spacing: 6) {
                    if !story.isRead {
                        Circle().fill(.tint).frame(width: 6, height: 6)
                    }
                    if story.eventCount > 1 {
                        Text("\(story.eventCount)×")
                            .padding(.horizontal, 4)
                            .background(.tertiary, in: RoundedRectangle(cornerRadius: 3))
                    }
                    if let s = story.topScore {
                        Text(String(format: "%.1f", s)).monospacedDigit()
                    }
                    Spacer()
                    Text(sidebarDate(story.lastUpdated))
                }
                .font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }
}

private struct SourceBadge: View {
    let source: String
    var body: some View {
        Image(systemName: icon)
            .foregroundStyle(color)
            .font(.system(size: 11, weight: .semibold))
            .frame(width: 18, height: 18)
            .background(color.opacity(0.15), in: RoundedRectangle(cornerRadius: 4))
            .help(source)
    }
    private var icon: String {
        switch source {
        case "hackernews": return "y.square.fill"
        case "reddit":     return "bubble.left.fill"
        case "rss":        return "dot.radiowaves.left.and.right"
        case "github":     return "chevron.left.forwardslash.chevron.right"
        case "twitter":    return "bird"
        case "telegram":   return "paperplane.fill"
        default:           return "doc"
        }
    }
    private var color: Color {
        switch source {
        case "hackernews": return .orange
        case "reddit":     return .red
        case "rss":        return .blue
        case "github":     return .purple
        case "twitter":    return .cyan
        case "telegram":   return .indigo
        default:           return .gray
        }
    }
}

private struct ChatPanel: View {
    @EnvironmentObject var model: AppModel
    @State private var draft: String = ""
    @FocusState private var inputFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(L10n.chatHeader).font(.headline)
                Spacer()
                if model.chatPending {
                    ProgressView().controlSize(.small)
                }
            }

            ForEach(model.currentMessages) { msg in
                ChatBubble(message: msg)
            }

            HStack(spacing: 8) {
                TextField(L10n.chatPlaceholder,
                          text: $draft, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.roundedBorder)
                    .focused($inputFocused)
                    .onSubmit(send)
                Button(action: send) {
                    Image(systemName: "paperplane.fill")
                }
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                          || model.chatPending)
                .keyboardShortcut(.return, modifiers: .command)
            }
        }
    }

    private func send() {
        let q = draft
        draft = ""
        model.ask(q)
        // Keep the input field hot so the user can fire follow-ups
        // without grabbing the mouse.
        inputFocused = true
    }
}

private struct ChatBubble: View {
    let message: ChatMessage
    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            if message.role == .user { Spacer(minLength: 60) }
            Group {
                if message.text.isEmpty {
                    HStack(spacing: 4) {
                        ProgressView().controlSize(.small)
                        Text(L10n.chatThinking).foregroundStyle(.secondary)
                    }
                } else {
                    Text(message.text).textSelection(.enabled)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(background, in: RoundedRectangle(cornerRadius: 8))
            .foregroundStyle(message.role == .error ? .red : .primary)
            if message.role != .user { Spacer(minLength: 60) }
        }
    }

    private var background: AnyShapeStyle {
        switch message.role {
        case .user:      return AnyShapeStyle(.tint.opacity(0.18))
        case .assistant: return AnyShapeStyle(.background.secondary)
        case .error:     return AnyShapeStyle(Color.red.opacity(0.12))
        }
    }
}

private struct UndoBanner: View {
    let undo: AppModel.DismissUndo
    let onUndo: () -> Void
    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "eye.slash")
            Text(L10n.dismissedBanner(undo.title))
                .lineLimit(1)
            Spacer()
            Button(L10n.undo, action: onUndo)
                .keyboardShortcut("z", modifiers: .command)
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(.regularMaterial, in: Capsule())
        .shadow(radius: 8, y: 2)
        .frame(maxWidth: 480)
    }
}

/// A simple wrapping row of tag pills. SwiftUI doesn't ship a flow layout
/// for macOS 14, so we use a HStack inside a ScrollView for horizontal
/// overflow — good enough at 3-5 tags per story.
private struct FlowChips: View {
    let tags: [String]
    let onTap: (String) -> Void
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(tags, id: \.self) { tag in
                    Button(action: { onTap(tag) }) {
                        Text(tag)
                            .font(.caption)
                            .padding(.horizontal, 8).padding(.vertical, 3)
                            .background(.tint.opacity(0.15), in: Capsule())
                            .foregroundStyle(.tint)
                    }
                    .buttonStyle(.plain)
                    .help("Filter by \(tag)")
                }
            }
        }
    }
}

private struct ThumbButton: View {
    let kind: Signals.Kind
    let current: Signals.Kind?
    let action: () -> Void

    var body: some View {
        let isActive = (current == kind)
        let icon = (kind == .thumbUp ? "hand.thumbsup" : "hand.thumbsdown")
            + (isActive ? ".fill" : "")
        return Button(action: action) {
            Image(systemName: icon)
                .foregroundStyle(isActive ? (kind == .thumbUp ? .green : .red) : .secondary)
        }
        .buttonStyle(.plain)
        .help(kind == .thumbUp ? L10n.thumbUpHelp : L10n.thumbDownHelp)
    }
}

private struct EventCard: View {
    let event: EventRow
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Text(displayDate(event.publishedAt))
                    .font(.caption).foregroundStyle(.secondary)
                Text(event.sourceType)
                    .font(.caption)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 4))
                if let score = event.aiScore {
                    Text(String(format: "%.1f", score))
                        .font(.caption).bold()
                }
                Spacer()
                if let url = URL(string: event.url) {
                    Link(destination: url) {
                        Image(systemName: "arrow.up.right.square")
                    }
                }
            }
            Text(event.title).font(.body)
            if let s = event.aiSummary, !s.isEmpty {
                Text(s).font(.callout).foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(.background.secondary, in: RoundedRectangle(cornerRadius: 8))
    }
}
