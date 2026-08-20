import AppKit

guard CommandLine.arguments.count == 3 else {
    fputs("Usage: render_feature_graphic.swift <icon.png> <output.jpg>\n", stderr)
    exit(2)
}

let iconPath = CommandLine.arguments[1]
let outputPath = CommandLine.arguments[2]
let canvas = NSImage(size: NSSize(width: 1024, height: 500))

func color(_ red: CGFloat, _ green: CGFloat, _ blue: CGFloat) -> NSColor {
    NSColor(red: red / 255, green: green / 255, blue: blue / 255, alpha: 1)
}

canvas.lockFocus()
color(245, 242, 233).setFill()
NSRect(x: 0, y: 0, width: 1024, height: 500).fill()

let titleAttributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 76, weight: .bold),
    .foregroundColor: color(31, 59, 37),
]
let bodyAttributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 30, weight: .regular),
    .foregroundColor: color(77, 98, 82),
]
let badgeAttributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 24, weight: .semibold),
    .foregroundColor: NSColor.white,
]

NSString(string: "Veggie Prep").draw(
    at: NSPoint(x: 78, y: 302),
    withAttributes: titleAttributes
)
NSString(string: "Your pantry. Practical meals.").draw(
    at: NSPoint(x: 82, y: 230),
    withAttributes: bodyAttributes
)
NSString(string: "Your choice of AI.").draw(
    at: NSPoint(x: 82, y: 184),
    withAttributes: bodyAttributes
)

let badge = NSBezierPath(roundedRect: NSRect(x: 82, y: 88, width: 292, height: 60), xRadius: 30, yRadius: 30)
color(46, 125, 50).setFill()
badge.fill()
NSString(string: "Local-first by design").draw(
    at: NSPoint(x: 112, y: 103),
    withAttributes: badgeAttributes
)

guard let icon = NSImage(contentsOfFile: iconPath) else {
    fputs("Could not open icon at \(iconPath)\n", stderr)
    exit(3)
}
icon.draw(in: NSRect(x: 676, y: 100, width: 300, height: 300))
canvas.unlockFocus()

guard
    let tiff = canvas.tiffRepresentation,
    let bitmap = NSBitmapImageRep(data: tiff),
    let jpeg = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.92])
else {
    fputs("Could not render feature graphic\n", stderr)
    exit(4)
}

try jpeg.write(to: URL(fileURLWithPath: outputPath), options: .atomic)
