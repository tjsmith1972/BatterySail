import AppKit
import Foundation

// BatterySail Menu — menu bar companion for the BatterySail daemon.
//
// Display-only. The root LaunchDaemon does all the SMC work and, every
// poll, publishes /etc/batterysail-state.json (world-readable). This
// app polls that file and shows the charge, ceiling, and mode in the
// menu bar. It writes nothing and needs no privileges.
//
// Build with scripts/install_menubar.sh (plain swiftc, no Xcode
// project, no third-party dependencies).

private let statePath = "/etc/batterysail-state.json"
private let logPath = "/var/log/batterysail.log"
private let staleAfter: TimeInterval = 90  // daemon polls every 30 s

private struct DaemonState: Decodable {
    let percent: Int
    let is_charging: Bool
    let external_connected: Bool
    let temperature_c: Double?
    let cycle_count: Int?
    let ceiling: Int?
    let mode: String?
    let enabled: Bool?
    let charge_limit: Int?
    let sailing_range: Int?
    let discharge_below: Int?
    let updated_at: String
}

private func modeLabel(_ mode: String?) -> String {
    switch mode {
    case "sailing": return "Sailing"
    case "charging": return "Charging"
    case "at_limit": return "At limit"
    case "heat_pause": return "Heat pause"
    case "discharging": return "Discharging"
    case "calibrating": return "Calibrating"
    case "off": return "Off"
    case "on_battery": return "On battery"
    case "holding": return "Holding"
    default: return "Unknown"
    }
}

private func modeDetail(_ state: DaemonState) -> String {
    let limit = state.charge_limit ?? 80
    let ceiling = state.ceiling ?? 100
    switch state.mode {
    case "sailing":
        return "charging held, battery drifting down to \(ceiling)%"
    case "charging":
        return "charging up to the \(limit)% limit"
    case "at_limit":
        return "holding at the \(limit)% limit"
    case "heat_pause":
        return "charging held while the battery is warm; resumes when it cools"
    case "discharging":
        return "ceiling pinned at \(state.discharge_below ?? ceiling)% until the battery falls to it"
    case "calibrating":
        return "calibration cycle, charging to 100%"
    case "off":
        return "BatterySail off, full charge allowed"
    case "on_battery":
        return "running on battery; ceiling \(ceiling)% applies on AC"
    case "holding":
        return "inside the sailing band, no change needed"
    default:
        return "—"
    }
}

private func parseISODate(_ text: String) -> Date? {
    let fractional = ISO8601DateFormatter()
    fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = fractional.date(from: text) { return date }
    let plain = ISO8601DateFormatter()
    plain.formatOptions = [.withInternetDateTime]
    if let date = plain.date(from: text) { return date }
    let manual = DateFormatter()
    manual.locale = Locale(identifier: "en_US_POSIX")
    manual.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXXXX"
    return manual.date(from: text)
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var timer: Timer?

    private let batteryItem = NSMenuItem(title: "Battery: —", action: nil, keyEquivalent: "")
    private let ceilingItem = NSMenuItem(title: "Ceiling: —", action: nil, keyEquivalent: "")
    private let modeItem = NSMenuItem(title: "Mode: —", action: nil, keyEquivalent: "")
    private let tempItem = NSMenuItem(title: "Temperature: —", action: nil, keyEquivalent: "")
    private let cyclesItem = NSMenuItem(title: "Cycles: —", action: nil, keyEquivalent: "")
    private let updatedItem = NSMenuItem(title: "Updated: —", action: nil, keyEquivalent: "")

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "BatterySail …"

        let menu = NSMenu()
        for item in [batteryItem, ceilingItem, modeItem, tempItem, cyclesItem, updatedItem] {
            menu.addItem(item)
        }
        menu.addItem(.separator())
        let logItem = NSMenuItem(title: "Open BatterySail Log", action: #selector(openLog), keyEquivalent: "")
        logItem.target = self
        menu.addItem(logItem)
        let quitItem = NSMenuItem(title: "Quit BatterySail Menu", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
        statusItem.menu = menu

        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    @objc private func openLog() {
        NSWorkspace.shared.open(URL(fileURLWithPath: logPath))
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }

    private func refresh() {
        guard let data = FileManager.default.contents(atPath: statePath),
              let state = try? JSONDecoder().decode(DaemonState.self, from: data),
              let updated = parseISODate(state.updated_at) else {
            showNotReporting("Daemon not reporting — no state file yet")
            return
        }
        if Date().timeIntervalSince(updated) > staleAfter {
            showNotReporting("Daemon not reporting — last update \(timeString(updated))")
            return
        }

        statusItem.button?.title = "\(state.percent)% · \(modeLabel(state.mode))"

        let power: String
        if !state.external_connected {
            power = "on battery"
        } else if state.is_charging {
            power = "charging"
        } else {
            power = "on AC, not charging"
        }
        batteryItem.title = "Battery: \(state.percent)% (\(power))"
        if let ceiling = state.ceiling, let limit = state.charge_limit {
            ceilingItem.title = "Ceiling: \(ceiling)%  (limit \(limit)%, sailing range \(state.sailing_range ?? 0)%)"
        } else {
            ceilingItem.title = "Ceiling: —"
        }
        modeItem.title = "Mode: \(modeLabel(state.mode)) — \(modeDetail(state))"
        if let temp = state.temperature_c {
            tempItem.title = String(format: "Temperature: %.1f °C", temp)
        } else {
            tempItem.title = "Temperature: —"
        }
        cyclesItem.title = "Cycles: \(state.cycle_count.map(String.init) ?? "—")"
        updatedItem.title = "Updated: \(timeString(updated))"
    }

    private func showNotReporting(_ message: String) {
        statusItem.button?.title = "BatterySail: ?"
        batteryItem.title = message
        ceilingItem.title = "Ceiling: —"
        modeItem.title = "Mode: —"
        tempItem.title = "Temperature: —"
        cyclesItem.title = "Cycles: —"
        updatedItem.title = "Updated: —"
    }

    private func timeString(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter.string(from: date)
    }
}

let delegate = AppDelegate()
let app = NSApplication.shared
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
