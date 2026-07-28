# Sender Actions



This guide explains how to display your actions in a conversation to let message recipients know that you have seen and are processing their message.

## Display a Sender Action {#example}

### Typing Indicator

To display the `typing_on` or `typing_off` actions in the for a sender in the conversation, send a POST request to the [`/me/messages` endpoint](https://developers.facebook.com/docs/graph-api/reference/page/messages) with the `sender_action` parameter set to `typing_on` or `typing_off`.

For the best conversational experience, send the `typing_on` indicator when your bot receives a message it will respond to. Do not allow an unnatural amount of time (too long or too short) to pass between `typing_on` and `typing_off` sender actions. Ideally, the user should feel that a real person was typing the message in the elapsed time.

```curl
curl -X POST -H "Content-Type: application/json" -d '{
  "recipient":{
    "id":"<IGSID>"
  },
  "sender_action":"typing_on"
}' "https://graph.facebook.com/VERSION/me/messages?access_token=INSTAGRAM_ACCESS_TOKEN"
```

### Mark messages as seen

To send the `mark_seen` indicator to the most recent message, send a `POST` request to the [`/me/messages` endpoint](https://developers.facebook.com/docs/graph-api/reference/page/messages) with the `sender_action` parameter set to `mark_seen`.

For the best conversational experience, send the `mark_seen` indicator when your bot receives a message so that the user does not feel ignored.

```curl
curl -X POST -H "Content-Type: application/json" -d '{
  "recipient":{
    "id":"<IGSID>"
  },
  "sender_action":"typing_on"
}' "https://graph.facebook.com/VERSION/me/messages?access_token=INSTAGRAM_ACCESS_TOKEN"
```

### Limitations

* Requests to display sender actions for typing indicators and `mark_seen` indicators should only include the `sender_action` parameter and the `recipient` object. All other Send API properties, such as text and templates, should be sent in a separate request.
* The recipient must be signed in for sender actions to be displayed.

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.

