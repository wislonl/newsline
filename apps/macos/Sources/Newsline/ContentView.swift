import SwiftUI

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
                        Label("\(story.eventCount) events", systemImage: "circle.dotted")
                        if let s = story.topScore {
                            Label(String(format: "top %.1f", s), systemImage: "star")
                        }
                        Text(story.lastUpdated.prefix(16))
                            .foregroundStyle(.secondary)
                    }
                    .font(.callout).foregroundStyle(.secondary)

                    if let summary = story.summary, !summary.isEmpty {
                        Text(summary).font(.body)
                    }

                    Divider().padding(.vertical, 8)
                    Text("Timeline").font(.headline)

                    ForEach(model.events) { e in
                        EventCard(event: e)
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
                Text("\(story.eventCount)")
                if let s = story.topScore {
                    Text(String(format: "· %.1f", s))
                }
                Spacer()
                Text(story.lastUpdated.prefix(10))
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
                if let when = event.publishedAt?.prefix(16) {
                    Text(when).font(.caption).foregroundStyle(.secondary)
                }
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
