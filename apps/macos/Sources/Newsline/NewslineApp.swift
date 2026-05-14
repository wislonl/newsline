import SwiftUI

@main
struct NewslineApp: App {
    @StateObject private var model = AppModel()

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

@MainActor
final class AppModel: ObservableObject {
    private let store = Store()
    @Published var stories: [StoryRow] = []
    @Published var selectedStoryID: String?
    @Published var events: [EventRow] = []
    @Published var dbExists: Bool = true

    init() { reload() }

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
