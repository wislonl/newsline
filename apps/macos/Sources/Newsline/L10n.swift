import Foundation

/// Tiny inline localization. We don't ship a Localizable.strings bundle
/// because SwiftPM macOS targets handle resources awkwardly without Xcode.
/// Switch is driven by the user's macOS language — set via System
/// Settings → Language & Region.
enum L10n {
    static var isChinese: Bool {
        let code = Locale.current.language.languageCode?.identifier
            ?? Locale.preferredLanguages.first?.split(separator: "-").first.map(String.init)
        return code == "zh"
    }

    // Window / menus
    static var windowTitle: String { isChinese ? "Newsline" : "Newsline" }
    static var fetchNow: String { isChinese ? "立即抓取" : "Fetch Now" }
    static var reloadView: String { isChinese ? "重新载入" : "Reload View" }
    static var fetchTooltip: String { isChinese ? "抓取新内容（⌘R）" : "Fetch new content (⌘R)" }
    static var fetchLabel: String { isChinese ? "抓取" : "Fetch" }

    // Empty states
    static var noDatabaseTitle: String { isChinese ? "数据库还没建好" : "No newsline database yet." }
    static var noDatabaseHint: String {
        isChinese ? "在终端执行 `news run` 抓一些内容。"
                  : "Run `news run` in the terminal to populate it."
    }
    static var noStoriesTitle: String { isChinese ? "暂无活跃故事线" : "No active storylines" }
    static var noStoriesHint: String { isChinese ? "试着点右上角“抓取”按钮。" : "Run the pipeline to create some." }
    static var selectStoryTitle: String { isChinese ? "选一个故事线" : "Select a storyline" }
    static var selectStoryHint: String {
        isChinese ? "从左侧选一个故事，查看完整时间线。"
                  : "Pick a story from the sidebar to view its timeline."
    }

    // Detail pane
    static var timelineHeader: String { isChinese ? "时间线" : "Timeline" }
    static var openLink: String { isChinese ? "打开原文" : "Open" }
    static func eventCount(_ n: Int) -> String {
        if isChinese { return "\(n) 条事件" }
        return "\(n) event" + (n == 1 ? "" : "s")
    }
    static func topScore(_ s: Double) -> String {
        if isChinese { return String(format: "最高 %.1f", s) }
        return String(format: "top %.1f", s)
    }

    // Sidebar sections + actions
    static var sectionToday: String { isChinese ? "今天" : "Today" }
    static var sectionYesterday: String { isChinese ? "昨天" : "Yesterday" }
    static var sectionThisWeek: String { isChinese ? "本周" : "This Week" }
    static var sectionOlder: String { isChinese ? "更早" : "Older" }
    static var showRead: String { isChinese ? "显示已读" : "Show Read" }
    static var dismissHelp: String { isChinese ? "屏蔽这条故事" : "Dismiss this story" }
    static var aiReasonLabel: String { isChinese ? "评分理由" : "Why this score" }

    // Chat
    static var chatHeader: String { isChinese ? "针对这个故事提问" : "Ask about this story" }
    static var chatPlaceholder: String {
        isChinese ? "发生了什么？为什么重要？……"
                  : "What changed? Why does this matter? …"
    }
    static var chatThinking: String { isChinese ? "思考中……" : "Thinking…" }
    static var thumbUpHelp: String { isChinese ? "标记感兴趣" : "Mark interesting" }
    static var thumbDownHelp: String { isChinese ? "标记不感兴趣" : "Mark not interesting" }
}

extension Date {
    /// Locale-aware "5月14日 / May 14"
    var newslineSidebarFormat: String {
        Self._sidebar.string(from: self)
    }
    /// Locale-aware "2026年5月14日 14:32 / May 14, 2026 at 2:32 PM"
    var newslineDetailFormat: String {
        Self._detail.string(from: self)
    }

    private static let _sidebar: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale.current
        f.setLocalizedDateFormatFromTemplate("MMMd")
        return f
    }()
    private static let _detail: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale.current
        f.dateStyle = .medium
        f.timeStyle = .short
        return f
    }()
}
