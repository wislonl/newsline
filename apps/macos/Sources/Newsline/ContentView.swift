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

private let displayFormatter: DateFormatter = {
    let f = DateFormatter()
    f.dateStyle = .medium
    f.timeStyle = .short
    return f
}()

private let sidebarDateFormatter: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "MMM d"
    return f
}()

/// Parse the timestamps written by the Python daemon (datetime.isoformat()).
/// They look like `2026-05-14T00:19:33.123456+00:00` or without fraction.
private func parseTimestamp(_ s: String?) -> Date? {
    guard let s, !s.isEmpty else { return nil }
    return isoParser.date(from: s) ?? isoParserNoFraction.date(from: s)
}

private func displayDate(_ s: String?) -> String {
    parseTimestamp(s).map(displayFormatter.string(from:)) ?? (s ?? "")
}

private func sidebarDate(_ s: String?) -> String {
    parseTimestamp(s).map(sidebarDateFormatter.string(from:)) ?? (s?.prefix(10).description ?? "")
}

private func pluralize(_ n: Int, _ singular: String) -> String {
    "\(n) \(singular)\(n == 1 ? "" : "s")"
}

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        NavigationSplitView {
            storyList
        } detail: {
            storyDetail
        }
        .navigationTitle("Newsline")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button(action: model.reload) {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
            }
        }
    }

    // MARK: - Sidebar: stories

    @ViewBuilder
    private var storyList: some View {
        if !model.dbExists {
            VStack(spacing: 8) {
                Text("No newsline database yet.").font(.headline)
                Text("Run `newsline run` in the terminal to populate it.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            .padding()
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if model.stories.isEmpty {
            ContentUnavailableView("No active storylines",
                                   systemImage: "newspaper",
                                   description: Text("Run the pipeline to create some."))
        } else {
            List(selection: Binding(
                get: { model.selectedStoryID },
                set: { model.select($0) }
            )) {
                ForEach(model.stories) { story in
                    StoryRowItem(story: story).tag(story.id)
                }
            }
            .listStyle(.sidebar)
        }
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
                        Label(pluralize(story.eventCount, "event"), systemImage: "circle.dotted")
                        if let s = story.topScore {
                            Label(String(format: "top %.1f", s), systemImage: "star")
                        }
                        Text(displayDate(story.lastUpdated))
                            .foregroundStyle(.secondary)
                        Spacer()
                        if let first = model.events.first,
                           let url = URL(string: first.url) {
                            Link(destination: url) {
                                Label("Open", systemImage: "arrow.up.right.square")
                            }
                        }
                    }
                    .font(.callout).foregroundStyle(.secondary)

                    if let summary = story.summary, !summary.isEmpty {
                        Text(summary).font(.body)
                    }

                    // For multi-event stories show the timeline. Single-event
                    // stories already showed everything above; no need to repeat.
                    if model.events.count > 1 {
                        Divider().padding(.vertical, 8)
                        Text("Timeline").font(.headline)
                        ForEach(model.events) { e in
                            EventCard(event: e)
                        }
                    }
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            ContentUnavailableView("Select a storyline",
                                   systemImage: "sidebar.left",
                                   description: Text("Pick a story from the sidebar to view its timeline."))
        }
    }
}

private struct StoryRowItem: View {
    let story: StoryRow
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(story.title)
                .lineLimit(2)
                .font(.callout)
            HStack(spacing: 6) {
                if story.eventCount > 1 {
                    Text("\(story.eventCount)×")
                        .padding(.horizontal, 4)
                        .background(.tertiary, in: RoundedRectangle(cornerRadius: 3))
                }
                if let s = story.topScore {
                    Text(String(format: "%.1f", s))
                }
                Spacer()
                Text(sidebarDate(story.lastUpdated))
            }
            .font(.caption2).foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
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
