import AppKit

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: render_app_icon.swift <output.png>\n", stderr)
    exit(2)
}

let outputPath = CommandLine.arguments[1]
guard let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: 512,
    pixelsHigh: 512,
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 0
) else {
    fputs("Could not create icon bitmap\n", stderr)
    exit(3)
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
guard let context = NSGraphicsContext.current?.cgContext else {
    fputs("Could not create icon graphics context\n", stderr)
    exit(4)
}
context.clear(CGRect(x: 0, y: 0, width: 512, height: 512))
context.translateBy(x: 0, y: 512)
context.scaleBy(x: 1, y: -1)

NSColor(red: 46 / 255, green: 125 / 255, blue: 50 / 255, alpha: 1).setFill()
NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: 512, height: 512), xRadius: 112, yRadius: 112).fill()

let whiteLeaf = NSBezierPath()
whiteLeaf.move(to: NSPoint(x: 256, y: 389))
whiteLeaf.curve(
    to: NSPoint(x: 194, y: 222),
    controlPoint1: NSPoint(x: 208, y: 326),
    controlPoint2: NSPoint(x: 184, y: 271)
)
whiteLeaf.curve(
    to: NSPoint(x: 324, y: 114),
    controlPoint1: NSPoint(x: 204, y: 168),
    controlPoint2: NSPoint(x: 247, y: 132)
)
whiteLeaf.curve(
    to: NSPoint(x: 256, y: 298),
    controlPoint1: NSPoint(x: 329, y: 192),
    controlPoint2: NSPoint(x: 309, y: 255)
)
whiteLeaf.curve(
    to: NSPoint(x: 256, y: 389),
    controlPoint1: NSPoint(x: 251, y: 328),
    controlPoint2: NSPoint(x: 251, y: 358)
)
whiteLeaf.close()
NSColor.white.setFill()
whiteLeaf.fill()

let greenLeaf = NSBezierPath()
greenLeaf.move(to: NSPoint(x: 237, y: 326))
greenLeaf.curve(
    to: NSPoint(x: 136, y: 238),
    controlPoint1: NSPoint(x: 223, y: 283),
    controlPoint2: NSPoint(x: 189, y: 253)
)
greenLeaf.curve(
    to: NSPoint(x: 237, y: 369),
    controlPoint1: NSPoint(x: 136, y: 302),
    controlPoint2: NSPoint(x: 170, y: 345)
)
greenLeaf.close()
NSColor(red: 156 / 255, green: 204 / 255, blue: 101 / 255, alpha: 1).setFill()
greenLeaf.fill()

NSGraphicsContext.restoreGraphicsState()

guard let png = bitmap.representation(using: .png, properties: [:]) else {
    fputs("Could not encode icon PNG\n", stderr)
    exit(5)
}
try png.write(to: URL(fileURLWithPath: outputPath), options: .atomic)
