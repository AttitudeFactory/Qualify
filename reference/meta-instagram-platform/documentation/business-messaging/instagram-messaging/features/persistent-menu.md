# The Persistent Menu



This document shows you how to programmatically add the Persistent Menu to your Instagram messaging experience.

## How it works

The Persistent Menu allows you to create and send a menu of the main features of your business, such as hours of operation, store locations, and products, is always visible in a person&#039;s Messenger conversation with your business.

When a person clicks an item in the menu, Meta sends a `postback` webhook notification to your server with information about which item the person selected and by whom, and the standard messaging window opens. You have 24 hours to respond to the person after the CTA.

## Limitations

* A menu is not updated in real time
    * Existing conversations will not see an updated menu unless a person refreshes their inbox; new conversations will see updated menus. Be sure your app can handle deprecated menu items.
* The `composer_input_disabled` parameter is not available
* The `webview_height_ratio` parameter is not available
* You cannot customize a menu based on the recipient&#039;s Page-scoped ID (PSID)

## Requirements &#123;#requirements&#125;

For the persistent menu to appear, the following criteria must be satisfied:

- You are running Messenger API support for Instagram v226 or above on iOS or Android.
- You have set up your Instagram professional account, Page, Developer account, and app to [successfully call Messenger API support for Instagram](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/get-started).

## Supported buttons &#123;#supported_buttons&#125;

The persistent menu is composed of an array of [buttons](https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages/buttons). The following button types are supported in the persistent menu:

- `web_url`: Specifies the item is a [URL button](https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages/buttons).
- `postback`: Specifies the item is a [postback button](https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages/buttons).

## Setting the persistent menu &#123;#set_menu&#125;

To set the persistent menu, send a `POST` request to the [Messenger Profile API](https://developers.facebook.com/documentation/business-messaging/messenger-platform/reference/messenger-profile-api) to set the `persistent_menu` property.

**Note:** To view recent changes to the persistent menu within the Instagram app, go to the messages inbox and swipe down to refresh.

```curl
curl -X POST -H &quot;Content-Type: application/json&quot; -d
&#039;&#123;
    &quot;persistent_menu&quot;: [
        &#123;
            &quot;locale&quot;: &quot;default&quot;,
            &quot;call_to_actions&quot;: [
                &#123;
                    &quot;type&quot;: &quot;postback&quot;,
                    &quot;title&quot;: &quot;Talk to an agent&quot;,
                    &quot;payload&quot;: &quot;CARE_HELP&quot;
                &#125;,
                &#123;access_token=&lt;ACCESS_TOKEN&gt;
                    &quot;type&quot;: &quot;postback&quot;,
                    &quot;title&quot;: &quot;Outfit suggestions&quot;,
                    &quot;payload&quot;: &quot;CURATION&quot;
                &#125;,
                &#123;
                    &quot;type&quot;: &quot;web_url&quot;,
                    &quot;title&quot;: &quot;Shop now&quot;,
                    &quot;url&quot;: &quot;https://www.originalcoastclothing.com/&quot;

                &#125;
            ]
        &#125;
    ]
&#125;&#039; &quot;https://graph.facebook.com/v25.0/me/messenger_profile?platform=instagram&amp;access_token=&lt;ACCESS_TOKEN&gt;&quot;
```

## Localization &#123;#localization&#125;

You may provide default and localized button text for the persistent menu that will be displayed based on a person&#039;s locale.

To do this, specify separate objects in the `persistent_menu` array for each locale by setting the `locale` property to a [supported locale](https://developers.facebook.com/documentation/business-messaging/messenger-platform/messenger-profile/supported-locales):

```http
&#123;
  &quot;locale&quot;:&quot;default&quot;,
  &quot;call_to_actions&quot;:[...]
&#125;,
&#123;
  &quot;locale: &quot;zh_CN&quot;,
  &quot;call_to_actions&quot;:[...]
&#125;
```

## Request examples

### GET request

```
curl -X GET &quot;https://graph.facebook.com/v12.0/me/messenger_profile?fields=persistent_menu&amp;platform=instagram&quot;
```

Result

```
&#123;
    &quot;data&quot;: [
      &#123;
        &quot;persistent_menu&quot;: [
            &#123;
              &quot;locale&quot;: &quot;default&quot;,
              &quot;call_to_actions&quot;: [
                  &#123;
                      &quot;type&quot;: &quot;postback&quot;,
                      &quot;title&quot;: &quot;Talk to an agent&quot;,
                      &quot;payload&quot;: &quot;CARE_HELP&quot;
                  &#125;,
                  &#123;
                      &quot;type&quot;: &quot;postback&quot;,
                      &quot;title&quot;: &quot;Outfit suggestions&quot;,
                      &quot;payload&quot;: &quot;CURATION&quot;
                  &#125;,
                  &#123;
                      &quot;type&quot;: &quot;web_url&quot;,
                      &quot;title&quot;: &quot;Shop now&quot;,
                      &quot;url&quot;: &quot;https://www.originalcoastclothing.com/&quot;

                  &#125;
              ]
            &#125;
        ]
      &#125;
  ]
&#125;
```

### DELETE request

```
curl -X DELETE &quot;https://graph.facebook.com/v12.0/me/messenger_profile?fields=[&quot;persistent_menu&quot;]&amp;platform=instagram&quot;
```

## Best practices &#123;#best_practices&#125;

Just like with buttons, menu items can produce a webview or postback.

✅ Use the menu as entry points for your Page&#039;s main features.

✅ Be descriptive: your menu lets people know what your Page&#039;s features are. The menu instantly lets users know how they can interact with your Page.

✅ Be selective: limit menu items to 5 for best user experience.

❌ Don&#039;t expect the menu to contain user-specific data. The menu can be localized, but will not contain user-specific data.

❌ Don&#039;t put a &quot;Menu&quot; button in the menu that sends the user a message containing a menu. Just put that content directly in the menu — that&#039;s what it&#039;s for!

❌ Don&#039;t put generic actions like &quot;Restart&quot; in the menu.

❌ Don&#039;t use the most prominent menu positions for secondary information like *about*, *terms of service*, *privacy policy*, or *powered by*. These take focus away from the core features of your Page.

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.

