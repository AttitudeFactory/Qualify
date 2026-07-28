# The Persistent Menu



The Persistent Menu allows you to create a menu of the main features of your business, such as hours of operation, store locations, and products, that is always visible in a person's Instagram conversation with your business.

When a person clicks an item in the menu, a `postback` webhook notification is sent to your server, with information about what item was select and by whom, and the standard messaging window opens. You have 24 hours to respond to the person after the CTA.

## Before you start

This guide assumes you have set up your webhooks server to receive notifications and subscribed your app to Instagram `messages` and `messaging_postbacks` events.

You will need:

* The ID for the Instagram professional account (`IG_ID`)
* the Instagram-scoped ID (`IGSID`) for the person to whom you are sending the message

#### Host URL
`https://graph.instagram.com`

**Note:** To view recent changes to the persistent menu within the Instagram app, go to the messages inbox and swipe down to refresh.

### Limitations

* A menu is not updated in real time
    * Existing conversations will not see an updated menu unless a person refreshes their inbox; new conversations will see updated menus. Be sure your app can handle deprecated menu items.
* The `composer_input_disabled` parameter is not available
* The `webview_height_ratio` parameter is not available
* You can not customize a menu based on the recipient's Instagram-scoped ID (IGSID)

### Button types

The persistent menu is composed of an array of buttons. The following button types are supported in the persistent menu:

#### URL Button {#url-button}

The URL Button opens a web page in the in-app browser. This allows you to enrich the conversation with a web-based experience, where you have the full development flexibility of the web. For example, you might display a product summary in-conversation, then use the URL button to open the full product page on your website.

#### Postback Button {#postback-button}

The postback button sends a [`messaging_postbacks`](https://developers.facebook.com/documentation/business-messaging/messenger-platform/reference/webhook-events/messaging_postbacks) event to your webhook with the string set in the `payload` property. This allows you to take arbitrary actions when the button is tapped. For example, you might display a list of products, then send the product ID in the postback to your webhook, where it can be used to query your database and return the product details as a structured message.

## Set a Persistent Menu {#set_menu}

To set a persistent menu, send a `POST` request to the `/<IG_ID>/messenger_profile` endpoint with the `platform` property set to `instagram` and `persistent_menu` property with `composer_input_disabled` set to `false`, `locale` set to `default` or the locale of your choice, and an array of `call_to_action` objects. Each `call_to_action` object defines a menu item with the following parameters:

* `title` set to the button text
* `type` set to `postback` or `web_url` button type
* `payload` for a `postback` button or `url` for a `web_url` button
* `webview_height_ratio` set to `full` for `web_url` buttons

### Localize a menu

To localize a menu, create a `call_to_actions` array for each locale. The locale code is a combination of ISO 639-1 language code and ISO 3166-1 country code.

#### Sample Request

_Formatted for readability._

```curl
`curl -X POST -H "Content-Type: application/json" -d '{
    "persistent_menu": [
        {
            "locale": "default",
            "call_to_actions": [
                {
                    "type": "postback",
                    "title": "Talk to an agent",
                    "payload": "CARE_HELP"
                },
                {
                    "type": "postback",
                    "title": "Outfit suggestions",
                    "payload": "CURATION"
                },
                {
                    "type": "web_url",
                    "title": "Shop now",
                    "url": "https://www.originalcoastclothing.com/"

                }
            ],
        }
    ]
}' "https://graph.instagram.com/v20.0/me/messenger_profile?access_token=INSTAGRAM_ACCESS_TOKEN"`
```

#### Sample Request to set multiple persistent menu based on locale

_Formatted for readability._

```curl
curl -X POST \
-H "Content-Type: application/json" \
-d '{
  "persistent_menu": [
    {
      "locale": "default",
      "call_to_actions": [
        {
          "type": "postback",
          "title": "Talk to an agent",
          "payload": "CARE_HELP"
      },
      {
          "type": "postback",
          "title": "Outfit suggestions",
          "payload": "CURATION"
      },
      {
          "type": "web_url",
          "title": "Shop now",
          "url": "https://www.originalcoastclothing.com/"

      }
      ]
    },
    {
       "locale": "zh_CN",
       "call_to_actions": [
        {
          "type": "postback",
          "title": "Talk to an agent",
          "payload": "CARE_HELP"
      },
      {
          "type": "postback",
          "title": "Outfit suggestions",
          "payload": "CURATION"
      },
      {
          "type": "web_url",
          "title": "Shop now",
          "url": "https://www.originalcoastclothing.com/"

      }
       ]
     }
  ]
}' "https://graph.instagram.com/v20.0/me/messenger_profile?access_token=INSTAGRAM_ACCESS_TOKEN"
```

## Get a persistent menu

To get the contents of a persistent menu, send a `GET` request to the `/<IG_ID>/messenger_profile` endpoint with the `platform` property set to `instagram` and `persistent_menu` property with the `fields` parameter set to `persistent_menu`.

#### Sample Request

_Formatted for readability._

```curl
curl -X GET "https://graph.instagram.com/v20.0/me/messenger_profile?fields=persistent_menu&access_token=INSTAGRAM_ACCESS_TOKEN"
```

On success your app receives a JSON response with the `persistent_menu` array of objects.

## Delete a persistent menu

To delete the contents of a persistent menu, send a `DELETE` request to the `/<IG_ID>` endpoint with the `fields` parameter set to `persistent_menu`.

#### Sample Request

_Formatted for readability._

```curl
curl -X DELETE -H "Content-Type: application/json" -d '{
    "fields": [
      "persistent_menu",
    ]
  }' "https://graph.instagram.com/v20.0/me/messenger_profile?access_token=INSTAGRAM_ACCESS_TOKEN"
```

On success your app receives a JSON response with `success` set to `true`.

## Best Practices {#best_practices}

✅ Use the menu as entry points for your business's main features.

✅ Be descriptive: your menu instantly lets users know how they can interact with your business.

✅ Be selective: limit your menu to 5 items for best user experience.

