// Remotion CLI config (Studio + `remotion bundle`). The HTTP server does not read this
// file: it configures the renderer directly in server/render.mjs.
import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
// The render service runs on Linux in Docker; multi-process Chromium is what Remotion
// documents for that image (CONTRACT §5).
Config.setChromiumMultiProcessOnLinux(true);
