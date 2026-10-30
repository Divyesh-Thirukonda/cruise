#import <Cocoa/Cocoa.h>
#import <ApplicationServices/ApplicationServices.h>
#import <AVFoundation/AVFoundation.h>

// A stable, visible macOS identity for the trusted Python helper and its children.
// Permission requests are initiated by the user's buttons, never by pairing.
@interface ModulateApp : NSObject <NSApplicationDelegate>
@property NSTask *helper;
@property NSWindow *window;
@property NSTextField *status;
@property BOOL stopping;
@end

@implementation ModulateApp
- (void)startHelper {
    NSDictionary *info = NSBundle.mainBundle.infoDictionary;
    self.helper = [NSTask new];
    self.helper.executableURL = [NSURL fileURLWithPath:info[@"ModulatePython"]];
    self.helper.currentDirectoryURL = [NSURL fileURLWithPath:info[@"ModulateRoot"]];
    self.helper.arguments = @[@"-u", @"-m", @"modulate.mac_companion"];
    self.helper.terminationHandler = ^(NSTask *task) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 3*NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            if (!self.stopping) [self startHelper];
        });
    };
    NSError *error = nil;
    if (![self.helper launchAndReturnError:&error]) self.status.stringValue = @"Helper could not start. Reinstall from the trusted Modulate checkout.";
}
- (void)screen:(id)sender {
    CGRequestScreenCaptureAccess();
    [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:@"x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"]];
}
- (void)accessibility:(id)sender {
    AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)@{(__bridge NSString *)kAXTrustedCheckOptionPrompt:@YES});
    [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:@"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"]];
}
- (void)camera:(id)sender {
    [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL granted) {}];
}
- (void)website:(id)sender {
    [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:@"https://modulate-connect.vercel.app/connect/setup"]];
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSMenu *menu = [NSMenu new]; NSMenuItem *app = [NSMenuItem new];
    [menu addItem:app]; app.submenu = [NSMenu new];
    [app.submenu addItemWithTitle:@"Quit Modulate" action:@selector(terminate:) keyEquivalent:@"q"];
    NSApp.mainMenu = menu;
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0,0,580,330)
        styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Modulate — Mac access";
    self.window.releasedWhenClosed = NO;
    NSTextField *title = [NSTextField labelWithString:@"Connect your Mac to Modulate"];
    title.font = [NSFont boldSystemFontOfSize:23]; title.frame = NSMakeRect(28,270,530,32);
    [self.window.contentView addSubview:title];
    self.status = [NSTextField wrappingLabelWithString:@"Allow Modulate in macOS Settings to read the screen and control apps. Camera access is optional. Your Pi works independently; closing this window keeps the Mac helper running."];
    self.status.frame = NSMakeRect(28,166,524,90); [self.window.contentView addSubview:self.status];
    NSArray *names = @[@"Screen & audio recording", @"Keyboard & mouse access", @"Camera", @"Open Modulate website"];
    SEL actions[] = {@selector(screen:),@selector(accessibility:),@selector(camera:),@selector(website:)};
    for (int i=0;i<4;i++) {
        NSButton *b = [NSButton buttonWithTitle:names[i] target:self action:actions[i]];
        b.frame = NSMakeRect(28+(i%2)*270,100-(i/2)*52,254,34); [self.window.contentView addSubview:b];
    }
    [self.window center]; [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
    [self startHelper];
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)visible {
    [self.window makeKeyAndOrderFront:nil]; return YES;
}
- (void)applicationWillTerminate:(NSNotification *)notification {
    self.stopping = YES; if (self.helper.running) [self.helper terminate];
}
@end

int main(int argc, const char **argv) {
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        ModulateApp *delegate = [ModulateApp new]; app.delegate = delegate;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular]; [app run];
    }
    return 0;
}
