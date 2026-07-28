# Sharing to Feed



With Sharing to Feed, you can allow your app&#039;s Users to share your content to their Instagram Feed.

## Overview

By using Android **Implicit Intents** and iOS **Universal Links** or **Document Interaction**, your app can pass photos and videos to the Instagram app. The Instagram app will receive this content and load it in the feed composer so the User can publish it to their Instagram Feed.

## Android Developers

Android implementations use implicit intents with the EXTRA_STREAM extra to prompt the User to select the Instagram app. Once selected, the intent will launch the Instagram app and pass it your content, which the Instagram App will then load in the Feed Composer.

In general, your sharing flow should:

1. Instantiate an implicit intent with the content you want to pass to the Instagram app.
2. Start an activity and check that it can resolve the implicit intent.
3. Resolve the activity if it is able to.

### Shareable Content

You can pass the following content to the Instagram app:

| Content | File Types | Description |
| --- | --- | --- |
| Image asset | JPEG, GIF, or PNG | - |
| File asset | MKV, MP4 | Minimum duration: 3 seconds&lt;br&gt;Maximum duration: 10 minutes&lt;br&gt;Minimum dimentions: 640x640 pixels |

### Sharing an Image Asset

```
String type = &quot;image/*&quot;;
String filename = &quot;/myPhoto.jpg&quot;;
String mediaPath = Environment.getExternalStorageDirectory() + filename;

createInstagramIntent(type, mediaPath);

private void createInstagramIntent(String type, String mediaPath)&#123;

    // Create the new Intent using the &#039;Send&#039; action.
    Intent share = new Intent(Intent.ACTION_SEND);

    // Set the MIME type
    share.setType(type);

    // Create the URI from the media
    File media = new File(mediaPath);
    Uri uri = Uri.fromFile(media);

    // Add the URI to the Intent.
    share.putExtra(Intent.EXTRA_STREAM, uri);

    // Broadcast the Intent.
    startActivity(Intent.createChooser(share, &quot;Share to&quot;));
&#125;
```

### Sharing a Video Asset

```
String type = &quot;video/*&quot;;
String filename = &quot;/myVideo.mp4&quot;;
String mediaPath = Environment.getExternalStorageDirectory() + filename;

createInstagramIntent(type, mediaPath);

private void createInstagramIntent(String type, String mediaPath)&#123;

    // Create the new Intent using the &#039;Send&#039; action.
    Intent share = new Intent(Intent.ACTION_SEND);

    // Set the MIME type
    share.setType(type);

    // Create the URI from the media
    File media = new File(mediaPath);
    Uri uri = Uri.fromFile(media);

    // Add the URI to the Intent.
    share.putExtra(Intent.EXTRA_STREAM, uri);

    // Broadcast the Intent.
    startActivity(Intent.createChooser(share, &quot;Share to&quot;));
&#125;
```

## iOS Developers

iOS implementations can use universal links to launch the Instagram app and pass it content, or have it perform a specific action.

### Universal Links

Use the [universal links](https://developer.apple.com/documentation/xcode/allowing-apps-and-websites-to-link-to-your-content) listed in the following table to perform actions in the Instagram app.

| Universal link | Action |
| --- | --- |
| https://www.instagram.com | Launch the Instagram app. |
| https://www.instagram.com/create/story | Launch the Instagram app with the camera view or photo library on non-camera devices. |
| https://www.instagram.com/p/&#123;media_id&#125; | Launch the Instagram app and load the post that matches the specified ID value (`int`). |
| https://www.instagram.com/&#123;username&#125; | Launch the Instagram app and load the Instagram user that matches the specified username value (`string`). |
| https://www.instagram.com/explore/locations/&#123;location_id&#125; | Launch the Instagram app and load the location feed that matches the specified ID value (`int`). |
| https://www.instagram.com/explore/tags/&#123;tag_name&#125; | Launch the Instagram app and load the page for the hashtag that matches the specified name value (`string`). |

### Sample Objective-C Code

The following example in Objective-C launches the Instagram app with the camera view.

```
NSURL *instagramURL = [NSURL URLWithString:&#064;&quot;https://www.instagram.com/create/story&quot;];
if ([[UIApplication sharedApplication] canOpenURL:instagramURL]) &#123;
    [[UIApplication sharedApplication] openURL:instagramURL];
&#125;
```

### Document Interaction

If your application creates photos and you&#039;d like your users to share these photos using Instagram, you can use the [Document Interaction API](https://developer.apple.com/library/content/documentation/FileManagement/Conceptual/DocumentInteraction_TopicsForIOS/Introduction/Introduction.html) to open your photo in Instagram&#039;s sharing flow.

You must first save your file in PNG or JPEG (preferred) format and use the filename extension `.ig`. Using the iOS Document Interaction APIs you can trigger the photo to be opened by Instagram. The Identifier for our Document Interaction UTI is `com.instagram.photo`, and it conforms to the *public/jpeg* and *public/png* UTIs. See the Apple documentation articles: [Previewing and Opening Files](https://developer.apple.com/library/content/documentation/FileManagement/Conceptual/DocumentInteraction_TopicsForIOS/Articles/PreviewingandOpeningItems.html#//apple_ref/doc/uid/TP40010410-SW1) and the [UIDocumentInteractionController Class Reference](https://developer.apple.com/library/content/#documentation/UIKit/Reference/UIDocumentInteractionController_class/Reference/Reference.html) for more information.

Alternatively, if you want to show **only** Instagram in the application list (instead of Instagram plus any other *public/jpeg*-conforming apps) you can specify the extension class `igo`, which is of type `com.instagram.exclusivegram`.

When triggered, Instagram will immediately present the user with our filter screen. The image is preloaded and sized appropriately for Instagram. For best results, Instagram prefers opening a JPEG that is 640px by 640px square. If the image is larger, it will be resized dynamically.
