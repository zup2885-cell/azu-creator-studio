#import <Cocoa/Cocoa.h>

@interface StudioLauncher : NSObject <NSApplicationDelegate>
@property(nonatomic,strong) NSTask *task;
@end

@implementation StudioLauncher
- (void)fail:(NSString *)message {
    [NSApp activateIgnoringOtherApps:YES];
    NSAlert *alert=[[NSAlert alloc] init];
    alert.messageText=@"创作台暂时无法启动";
    alert.informativeText=message;
    [alert addButtonWithTitle:@"好"];
    [alert runModal];
    [NSApp terminate:nil];
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSURL *configURL=[[NSBundle mainBundle] URLForResource:@"launcher-config" withExtension:@"json"];
    NSData *configData=configURL?[NSData dataWithContentsOfURL:configURL]:nil;
    NSDictionary *config=configData?[NSJSONSerialization JSONObjectWithData:configData options:0 error:nil]:nil;
    NSString *python=config[@"python"], *launcher=config[@"launcher"];
    if(!python || !launcher || ![[NSFileManager defaultManager] isExecutableFileAtPath:python] || ![[NSFileManager defaultManager] isReadableFileAtPath:launcher]) {
        [self fail:@"找不到启动文件。请保留桌面的「抖音数据看板」文件夹，并确认 TzFilm 的 Python 环境仍然存在。"];
        return;
    }
    self.task=[[NSTask alloc] init];
    self.task.executableURL=[NSURL fileURLWithPath:python];
    self.task.arguments=@[launcher,@"--open"];
    self.task.currentDirectoryURL=[[NSURL fileURLWithPath:launcher] URLByDeletingLastPathComponent];
    NSPipe *output=[NSPipe pipe];
    self.task.standardOutput=output;
    self.task.standardError=output;
    __weak StudioLauncher *weakSelf=self;
    self.task.terminationHandler=^(NSTask *finished) {
        NSData *data=[[output fileHandleForReading] readDataToEndOfFile];
        NSString *text=[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding]?:@"";
        NSString *logDir=[NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/TzFilmDouyin/logs"];
        [[NSFileManager defaultManager] createDirectoryAtPath:logDir withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *logPath=[logDir stringByAppendingPathComponent:@"desktop-launcher.log"];
        NSString *entry=[NSString stringWithFormat:@"%@ status=%d %@\n",[NSDate date],finished.terminationStatus,text];
        NSData *entryData=[entry dataUsingEncoding:NSUTF8StringEncoding];
        if(![[NSFileManager defaultManager] fileExistsAtPath:logPath]) {
            [[NSFileManager defaultManager] createFileAtPath:logPath contents:nil attributes:@{NSFilePosixPermissions:@0600}];
        }
        NSFileHandle *handle=[NSFileHandle fileHandleForWritingAtPath:logPath];
        [handle seekToEndOfFile];[handle writeData:entryData];[handle closeFile];
        dispatch_async(dispatch_get_main_queue(),^{
            if(finished.terminationStatus!=0) [weakSelf fail:text.length?text:@"本地服务未能启动，请检查项目文件夹或端口占用。"];
            else [NSApp terminate:nil];
        });
    };
    NSError *error=nil;
    if(![self.task launchAndReturnError:&error]) [self fail:error.localizedDescription];
}
@end

int main(int argc,const char *argv[]) {
    @autoreleasepool {
        NSApplication *app=[NSApplication sharedApplication];
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        StudioLauncher *delegate=[[StudioLauncher alloc] init];
        app.delegate=delegate;
        [app run];
    }
    return 0;
}
