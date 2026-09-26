// 离屏渲染 + 可见性测量：给 dashboard.html 生成截图，并回答"这个元素在屏幕上
// 真正可见吗"。
//
// 动机：DOM 里存在 ≠ 屏幕上可见。本项目的两个真实缺陷都属此类——
//   1) 确认框写进了普通 <div>，被 showModal() 提进 top layer 的结果面板整个盖住，
//      表现为"点了没反应、只闪一下"；
//   2) 挂在 <section class="hidden"> 内的 <dialog>，即便 showModal() 成功
//      （open=true、:modal 匹配），祖先 display:none 也会让它拿不到尺寸（rect=0x0）。
// 单看 innerHTML 或 open 属性都会误判，所以这里既截图，也取元素中心点用
// elementFromPoint 问"这一点上最顶层的是谁"。
//
// 用法：
//   swift tools/shot_dialog.swift <input.html> <output.png> [选项]
//
// 选项：
//   --wait <秒>        加载完成后等待多久再测量/截图（默认 3）
//   --target <id>      要测量的元素 id，可重复；默认测页面里所有 <dialog>
//   --timeout <秒>     总超时（默认 60）
//   --size <宽>x<高>   视口尺寸（默认 1280x860）
//
// 兼容环境变量 SHOT_WAIT / SHOT_TARGET（单值）。命令行参数优先。
// 未识别的参数会明确报错退出，不静默忽略——参数被悄悄丢弃会导致"探针明明设了
// 等待时间却总在 3 秒测量"这类假阴性，本项目踩过一次。
import Cocoa
import WebKit
import Foundation

private func fail(_ msg: String) -> Never {
    FileHandle.standardError.write(Data(("shot_dialog: " + msg + "\n").utf8))
    exit(64)   // EX_USAGE
}

let argv = CommandLine.arguments
guard argv.count >= 3 else {
    fail("用法: swift tools/shot_dialog.swift <input.html> <output.png> [--wait 秒] [--target id] [--timeout 秒] [--size 宽x高]")
}
let inputPath = argv[1], outputPath = argv[2]

let env = ProcessInfo.processInfo.environment
var waitSec = Double(env["SHOT_WAIT"] ?? "") ?? 3.0
var timeoutSec = 60.0
var viewW: CGFloat = 1280, viewH: CGFloat = 860
// 环境变量提供默认值；命令行一旦显式给出同名选项就整体接管（而不是叠加），
// 否则 SHOT_TARGET 与 --target 会同时生效，测出一堆没打算测的目标。
let envTarget = env["SHOT_TARGET"].map { [$0] } ?? []
var targets: [String] = []
var targetsFromCLI = false

var i = 3
while i < argv.count {
    let arg = argv[i]
    func value(_ name: String) -> String {
        guard i + 1 < argv.count else { fail("\(name) 缺少取值") }
        i += 1
        return argv[i]
    }
    switch arg {
    case "--wait":    guard let v = Double(value(arg)), v >= 0 else { fail("--wait 需要一个非负秒数") }; waitSec = v
    case "--timeout": guard let v = Double(value(arg)), v > 0 else { fail("--timeout 需要一个正秒数") }; timeoutSec = v
    case "--target":
        if !targetsFromCLI { targets = []; targetsFromCLI = true }   // 首个 --target 丢掉环境变量
        targets.append(value(arg))
    case "--size":
        let parts = value(arg).split(separator: "x")
        guard parts.count == 2, let w = Double(parts[0]), let h = Double(parts[1]), w > 0, h > 0 else {
            fail("--size 形如 1280x860")
        }
        viewW = CGFloat(w); viewH = CGFloat(h)
    default: fail("未识别的参数 \(arg)")
    }
    i += 1
}

// 命令行没给 --target 时，才回退到环境变量（空数组=自动测所有 dialog）
if !targetsFromCLI { targets = envTarget }

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)

final class Shot: NSObject, WKNavigationDelegate {
    var web: WKWebView!
    var done = false

    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
        DispatchQueue.main.asyncAfter(deadline: .now() + waitSec) { [self] in
            guard !done else { return }
            done = true
            measureAndSnap(w)
        }
    }

    /// 测量目标元素的真实可见性。多个目标一起报，便于横向对照
    /// （此后能一眼看出"同在一处的 A 可见、B 不可见"这种差异）。
    private func jsFor(_ ids: [String]) -> String {
        let list = ids.map { "\"\($0)\"" }.joined(separator: ",")
        return """
        (function(){
          var ids = [\(list)];
          if (!ids.length) {
            ids = Array.prototype.map.call(document.querySelectorAll('dialog[id]'), function(d){ return d.id; });
          }
          function at(x,y){ var e=document.elementFromPoint(x,y); if(!e) return 'null';
                            return (e.id ? '#'+e.id : (e.className||e.tagName)); }
          return ids.map(function(id){
            var p = document.getElementById(id);
            if (!p) return id + ':missing';
            var r = p.getBoundingClientRect();
            var visible = r.width > 0 && r.height > 0;
            var topIsSelf = false;
            if (visible) {
              var e = document.elementFromPoint(r.left + r.width/2, Math.min(r.top + r.height/2, innerHeight-1));
              topIsSelf = !!(e && (e === p || p.contains(e)));
            }
            return id
              + ' open=' + (p.open === undefined ? '-' : p.open)
              + ' modal=' + (p.matches && p.matches(':modal'))
              + ' rect=' + [r.left,r.top,r.width,r.height].map(Math.round).join(',')
              + ' visible=' + visible
              + ' topIsSelf=' + topIsSelf;
          }).join(' | ') + ' title=' + document.title;
        })();
        """
    }

    private func measureAndSnap(_ w: WKWebView) {
        w.evaluateJavaScript(jsFor(targets)) { result, error in
            print("MEASURE: " + (error != nil ? "ERR \(error!.localizedDescription)"
                                              : (result as? String ?? "nil")))
            let cfg = WKSnapshotConfiguration()
            cfg.rect = CGRect(x: 0, y: 0, width: viewW, height: viewH)
            cfg.afterScreenUpdates = true
            w.takeSnapshot(with: cfg) { image, _ in
                guard let img = image,
                      let tiff = img.tiffRepresentation,
                      let rep = NSBitmapImageRep(data: tiff),
                      let png = rep.representation(using: .png, properties: [:]) else {
                    print("SNAP fail"); exit(1)
                }
                do {
                    try png.write(to: URL(fileURLWithPath: outputPath))
                    print("SNAP ok -> \(outputPath)")
                    exit(0)
                } catch {
                    print("SNAP 写入失败: \(error.localizedDescription)"); exit(1)
                }
            }
        }
    }
}

let shot = Shot()
shot.web = WKWebView(frame: NSRect(x: 0, y: 0, width: viewW, height: viewH))
let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: viewW, height: viewH),
                   styleMask: [.borderless], backing: .buffered, defer: false)
win.contentView = shot.web
shot.web.navigationDelegate = shot
shot.web.loadFileURL(URL(fileURLWithPath: inputPath),
                     allowingReadAccessTo: URL(fileURLWithPath: inputPath).deletingLastPathComponent())

DispatchQueue.main.asyncAfter(deadline: .now() + timeoutSec) {
    print("TIMEOUT: \(timeoutSec) 秒内未完成（页面可能未触发 didFinish）")
    exit(2)
}
app.run()
