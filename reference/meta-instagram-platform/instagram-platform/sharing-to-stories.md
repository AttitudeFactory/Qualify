# Sharing to Stories



You can integrate sharing into your Android and iOS apps so that users can share your content as an Instagram story. To create a new app, see [Getting Started with the Facebook SDK for Android](https://developers.facebook.com/documentation/android/getting-started) and [Getting Started with the Facebook SDK for iOS](https://developers.facebook.com/documentation/ios/getting-started).

**Warning:** Beginning in January 2023, you must provide a Facebook AppID to share content to Instagram Stories. For more information, see [Introducing an important update to Instagram Sharing to Stories](https://developers.facebook.com/blog/post/2022/10/10/introducing-important-update-to-Instagram-sharing-to-stories/). If you don't provide an AppID, your users see the error message "The app you shared from doesn't currently support sharing to Stories" when they attempt to share their content to Instagram.  To find your App ID, see [Get Your App ID (Android)](https://developers.facebook.com/documentation/android/getting-started#app-id) and [Get Your App ID (iOS)](https://developers.facebook.com/documentation/ios/getting-started#app-id).

## Overview

By using Android **Implicit Intents** and iOS **Custom URL Schemes**, your app can send photos, videos, and stickers to the Instagram app. The Instagram app receives this content and load it in the story composer so the User can publish it to their Instagram Stories.

The Instagram app's story composer is comprised of a background layer and a sticker layer.

#### Background Layer

The background layer fills the screen and you can customize it with a photo, video, solid color, or color gradient.

#### Sticker Layer

The sticker layer can contain an image, and the layer can be further customized by the User within the story composer.

## Android Developers

Android implementations use implicit intents to launch the Instagram app and pass it content. In general, your sharing flow should:

1. Instantiate an implicit intent with the content you want to pass to the Instagram app.
2. Start an activity and check that it can resolve the implicit intent.
3. Resolve the activity if it is able to.

### Data

You send the following data when you share to Stories.

| Content | Type | Description |
| --- | --- | --- |
| Facebook App ID | String | Your [Facebook App ID](https://developers.facebook.com/documentation/android/getting-started#app-id). |
| Background asset | [Uri](https://developer.android.com/reference/android/net/Uri) | Uri to an image asset (JPG, PNG) or video asset (H.264, H.265, WebM). Minimum dimensions 720x1280. Recommended image ratios 9:16 or 9:18. Videos can be 1080p and up to 20 seconds in duration. **The Uri needs to be a content Uri to a local file on the device**. You must send a background asset, a sticker asset, or both. |
| Sticker asset | [Uri](https://developer.android.com/reference/android/net/Uri) | Uri to an image asset (JPG, PNG). Recommended dimensions: 640x480. This image appears as a sticker over the background. **The Uri needs to be a content Uri to a local file on the device**. You must send a background asset, a sticker asset, or both. |
| Background layer top color | String | A hex string color value used in conjunction with the background layer bottom color value. If both values are the same, the background layer is a solid color. If they differ, they are used to generate a gradient. If you specify a background asset, the asset is used and this value is ignored. |
| Background layer bottom color | String | A hex string color value used in conjunction with the background layer top color value. If both values are the same, the background layer is a solid color. If they differ, they are used to generate a gradient. If you specify a background asset, the asset is used and this value is ignored. |

### Sharing a Background Asset

The following code example sends an image to Instagram so the user can publish it to their Instagram Stories.

```
// Instantiate an intent
Intent intent = new Intent("com.instagram.share.ADD_TO_STORY");

// Attach your App ID to the intent
String sourceApplication = "1234567"; // This is your application's FB ID
intent.putExtra("source_application", sourceApplication);

// Attach your image to the intent from a URI
Uri backgroundAssetUri = Uri.parse("your-image-asset-uri-goes-here");
intent.setDataAndType(backgroundAssetUri, MEDIA_TYPE_JPEG);

// Grant URI permissions for the image
intent.setFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);

// Instantiate an activity
Activity activity = getActivity();

// Verify that the activity resolves the intent and start it
if (activity.getPackageManager().resolveActivity(intent, 0) != null) {
  activity.startActivityForResult(intent, 0);
}
```

### Sharing a Sticker Asset

This example sends a sticker layer image asset and a set of background layer colors to Instagram. If you don't specify the background layer colors, the background layer color is `#222222`.

```
// Instantiate an intent
Intent intent = new Intent("com.instagram.share.ADD_TO_STORY");

// Attach your App ID to the intent
String sourceApplication = "1234567"; // This is your application's FB ID
intent.putExtra("source_application", sourceApplication);

// Attach your sticker to the intent from a URI, and set background colors
Uri stickerAssetUri = Uri.parse("your-image-asset-uri-goes-here");
intent.setType(MEDIA_TYPE_JPEG);
intent.putExtra("interactive_asset_uri", stickerAssetUri);
intent.putExtra("top_background_color", "#33FF33");
intent.putExtra("bottom_background_color", "#FF00FF");

// Instantiate an activity
Activity activity = getActivity();

// Grant URI permissions for the sticker
activity.grantUriPermission(
    "com.instagram.android", stickerAssetUri, Intent.FLAG_GRANT_READ_URI_PERMISSION);

// Verify that the activity resolves the intent and start it
if (activity.getPackageManager().resolveActivity(intent, 0) != null) {
  activity.startActivityForResult(intent, 0);
}
```

### Sharing a Background Asset and a Sticker Asset

This example sends a background layer image asset and a sticker layer image asset to Instagram.

```
// Instantiate an intent
Intent intent = new Intent("com.instagram.share.ADD_TO_STORY");

// Attach your App ID to the intent
String sourceApplication = "1234567"; // This is your application's FB ID
intent.putExtra("source_application", sourceApplication);

// Attach your image to the intent from a URI
Uri backgroundAssetUri = Uri.parse("your-background-image-asset-uri-goes-here");
intent.setDataAndType(backgroundAssetUri, MEDIA_TYPE_JPEG);

// Attach your sticker to the intent from a URI
Uri stickerAssetUri = Uri.parse("your-sticker-image-asset-uri-goes-here");
intent.putExtra("interactive_asset_uri", stickerAssetUri);

// Grant URI permissions for the image
intent.setFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);

// Instantiate an activity
Activity activity = getActivity();

// Grant URI permissions for the sticker
activity.grantUriPermission(
    "com.instagram.android", stickerAssetUri, Intent.FLAG_GRANT_READ_URI_PERMISSION);

// Verify that the activity resolves the intent and start it
if (activity.getPackageManager().resolveActivity(intent, 0) != null) {
  activity.startActivityForResult(intent, 0);
}
```

## iOS Developers

iOS implementations use a **custom URL scheme** to launch the Instagram app and pass it content. In general, your sharing flow should:

1. Check that your app can resolve Instagram's custom URL scheme.
2. Assign the content that you want to share to the pasteboard.
3. Resolve the custom URL scheme if your app is able to.

### Data

You send the following data when you share to Stories.

| Content | Type | Description |
| --- | --- | --- |
| Facebook App ID | [NSString *](https://developer.apple.com/documentation/foundation/nsstring/) | Your [Facebook App ID](https://developers.facebook.com/documentation/ios/getting-started#app-id). |
| Background image asset | [NSData *](https://developer.apple.com/documentation/foundation/nsdata/) | Data for an image asset in a supported format (JPG, PNG). Minimum dimensions 720x1280. Recommended image ratios 9:16 or 9:18. You must pass the Instagram app a background asset (image or video), a sticker asset, or both. |
| Background video asset | [NSData *](https://developer.apple.com/documentation/foundation/nsdata/) | Data for video asset in a supported format (H.264, H.265, WebM). Videos can be 1080p and up to 20 seconds in duration. Under 50 MB recommended. You must pass the Instagram app a background asset (image or video), a sticker asset, or both. |
| Sticker asset | [NSData *](https://developer.apple.com/documentation/foundation/nsdata/) | Data for an image asset in a supported format (JPG, PNG). Recommended dimensions: 640x480. This image appears as a sticker over the background. You must pass the Instagram app a background asset (image or video), a sticker asset, or both. |
| Background layer top color | [NSString *](https://developer.apple.com/documentation/foundation/nsstring/) | A hex string color value used in conjunction with the background layer bottom color value. If both values are the same, the background layer is a solid color. If they differ, they are used to generate a gradient. |
| Background layer bottom color | [NSString *](https://developer.apple.com/documentation/foundation/nsstring/) | A hex string color value used in conjunction with the background layer bottom color value. If both values are the same, the background layer is a solid color. If they differ, they are used to generate a gradient. |

### Register Instagram's Custom URL Scheme

You need to register Instagram's custom URL scheme before your app use it. Add `instagram-stories` to the `LSApplicationQueriesSchemes` key in your app's `Info.plist`.

### Sharing a Background Asset

The following code example sends a background layer image asset to Instagram so the user can edit and publish it to their Instagram Stories.

```
- (void)shareBackgroundImage
{
  // Identify your App ID
  NSString *const appIDString = @"1234567890";

  // Call method to share image
  [self backgroundImage:UIImagePNGRepresentation([UIImage imageNamed:@"backgroundImage"])
        appID:appIDString];
}

// Method to share image
- (void)backgroundImage:(NSData *)backgroundImage
        appID:(NSString *)appID
{
  NSURL *urlScheme = [NSURL URLWithString:[NSString stringWithFormat:@"instagram-stories://share?source_application=%@", appID]];

  if ([[UIApplication sharedApplication] canOpenURL:urlScheme])
  {
    // Attach the pasteboard items
    NSArray *pasteboardItems = @[@{@"com.instagram.sharedSticker.backgroundImage" : backgroundImage}];

    // Set pasteboard options
    NSDictionary *pasteboardOptions = @{UIPasteboardOptionExpirationDate : [[NSDate date] dateByAddingTimeInterval:60 * 5]};

    // This call is iOS 10+, can use 'setItems' depending on what versions you support
    [[UIPasteboard generalPasteboard] setItems:pasteboardItems options:pasteboardOptions];

    [[UIApplication sharedApplication] openURL:urlScheme options:@{} completionHandler:nil];
  }
  else
  {
      // Handle error cases
  }
}
```

### Sharing a Sticker Asset

This sample code shows how to pass the Instagram app a sticker layer image asset and a set of background layer colors. If you don't specify the background layer colors, the background layer color is `#222222`.

```
- (void)shareStickerImage
{
  // Identify your App ID
  NSString *const appIDString = @"1234567890";

  // Call method to share sticker
  [self stickerImage:UIImagePNGRepresentation([UIImage imageNamed:@"stickerImage"])
        backgroundTopColor:@"#444444"
        backgroundBottomColor:@"#333333"
        appID:appIDString];
}

// Method to share sticker
- (void)stickerImage:(NSData *)stickerImage
        backgroundTopColor:(NSString *)backgroundTopColor
        backgroundBottomColor:(NSString *)backgroundBottomColor
        appID:(NSString *)appID
{
  NSURL *urlScheme = [NSURL URLWithString:[NSString stringWithFormat:@"instagram-stories://share?source_application=%@", appID]];

  if ([[UIApplication sharedApplication] canOpenURL:urlScheme])
  {
    // Attach the pasteboard items
    NSArray *pasteboardItems = @[@{@"com.instagram.sharedSticker.stickerImage" : stickerImage,
                                   @"com.instagram.sharedSticker.backgroundTopColor" : backgroundTopColor,
                                   @"com.instagram.sharedSticker.backgroundBottomColor" : backgroundBottomColor}];

    // Set pasteboard options
    NSDictionary *pasteboardOptions = @{UIPasteboardOptionExpirationDate : [[NSDate date] dateByAddingTimeInterval:60 * 5]};

    // This call is iOS 10+, can use 'setItems' depending on what versions you support
    [[UIPasteboard generalPasteboard] setItems:pasteboardItems options:pasteboardOptions];

    [[UIApplication sharedApplication] openURL:urlScheme options:@{} completionHandler:nil];
  }
  else
  {
      // Handle error cases
  }
}
```

### Sharing a Background Asset and Sticker Asset

This sample code shows how to pass the Instagram app a background layer image asset and a sticker layer image asset.

```
- (void)shareBackgroundAndStickerImage
{
  // Identify your App ID
  NSString *const appIDString = @"1234567890";

  // Call method to share image and sticker
  [self backgroundImage:UIImagePNGRepresentation([UIImage imageNamed:@"backgroundImage"])
        stickerImage:UIImagePNGRepresentation([UIImage imageNamed:@"stickerImage"])
        appID:appIDString];
}

// Method to share image and sticker
- (void)backgroundImage:(NSData *)backgroundImage
        stickerImage:(NSData *)stickerImage
        appID:(NSString *)appID
{
  NSURL *urlScheme = [NSURL URLWithString:[NSString stringWithFormat:@"instagram-stories://share?source_application=%@", appID]];

  if ([[UIApplication sharedApplication] canOpenURL:urlScheme])
  {
    // Attach the pasteboard items
    NSArray *pasteboardItems = @[@{@"com.instagram.sharedSticker.backgroundImage" : backgroundImage,
                                   @"com.instagram.sharedSticker.stickerImage" : stickerImage}];

    // Set pasteboard options
    NSDictionary *pasteboardOptions = @{UIPasteboardOptionExpirationDate : [[NSDate date] dateByAddingTimeInterval:60 * 5]};

    // This call is iOS 10+, can use 'setItems' depending on what versions you support
    [[UIPasteboard generalPasteboard] setItems:pasteboardItems options:pasteboardOptions];

    [[UIApplication sharedApplication] openURL:urlScheme options:@{} completionHandler:nil];
  }
  else
  {
      // Handle error cases
  }
}
```

## Sharing to Facebook Stories

You can also allow your app's Users to share your content as a Facebook story. To learn how to do this, please refer to our Facebook [Sharing to Stories documentation](https://developers.facebook.com/documentation/sharing/sharing-to-stories).
