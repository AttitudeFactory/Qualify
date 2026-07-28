# Setup Webhooks Subscriptions



This document shows you how to create an endpoint on your server to receive webhook notifications from Meta and subscribe to webhook fields for an Instagram professional account using your app. This allows you to receive real-time notifications whenever someone comments on the Media objects of the Instagram professional account using your app, &#064;mentions your app users, when your app users&#039; Stories expire, or when a Instagram user sends a message to that Instagram professional account.

## The steps

The steps required to receive webhook notifications are as follows:

* **Step 1.** [Create an endpoint](#create-an-endpoint) on your server to receive webhooks from Meta
    * Verify requests from Meta – Occurs in the Meta App Dashboard
    * Accept and validate JSON payloads from Meta – Occurs on your server
* **Step 2.** Subscribe your app to webhook fields – Occurs in the Meta App Dashboard
* **Step 3.** Enable your app user&#039;s Instagram professional account to receive notifications via an API call to Meta
* **Step 4.** Test the setup by sending a message to your Instagram professional account.

### Sample app on Github

We provide a
[sample app on GitHub](https://github.com/fbsamples/graph-api-webhooks-samples)
that deploys on
[Heroku](https://www.heroku.com)
which you can set up and repurpose, or which you can use to quickly test your Webhooks configuration.

You need the following:

* A free Heroku account,
* Your app&#039;s App Secret found on Meta App Dashboard **App settings &gt; Basic**
* A Verify token which is a string. In your Heroku app&#039;s settings, set up two config vars: `APP_SECRET` and `TOKEN`. Set `APP_SECRET` to your app&#039;s App Secret and `TOKEN` to your password. We will include this string in any verification requests when you configure the Webhooks product in the App Dashboard (the app will validate the request on its own).

* View your Heroku app in a web browser. You should see an empty array (`[]`). This page will display newly received update notification data, so reload it throughout testing.
* Your app&#039;s Callback URL will be your Heroku app&#039;s URL with `/facebook` added to the end. You will need this Callback URL during product configuration.
* Copy the `TOKEN` value you set above; you&#039;ll also need this during product configuration.

#### What&#039;s in the Heroku sample app?

The app uses Node.js and these packages:

* `body-parser` (for parsing JSON)
* `express` (for routes)
* `express-x-hub` (for SHA1 support)

## Verifying the Sample App

You can easily verify that your sample app can receive Webhook events.

1. Under the **Webhooks** product in your App Dashboard, click the **Test** button for any of the Webhook fields.
1. A pop-up dialog will appear showing a sample of what will be sent.  Click **Send to My Server**.
1. You should now see the Webhook information at the Heroku app&#039;s URL, or use `curl https://&lt;your-subdomain&gt;.herokuapp.com` in a terminal window.

## Requirements

You will need:

* Your app must be set to **Live** in the App Dashboard for Meta to send webhook notifications

| Component | Business Login for Instagram | Facebook Login for Business | Instagram Messaging via Messenger Platform |
| --- | --- | --- | --- |
| **Access level** | Advanced Access | Advanced Access for `comments` and `live_comments` | Advanced Access |
| **Access tokens** | Instagram User access token | Facebook User or Page access token | Facebook User or Page access token |
| **Business Verification** | Required | Required | Required |
| **Base URL** | `graph.instagram.com` | `graph.facebook.com` | `graph.facebook.com` |
| **Endpoints** | [`/&lt;INSTAGRAM_ACCOUNT_ID&gt;`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) or `/me` – Represents your app user&#039;s Instagram profession account | [`/&lt;PAGE_ID&gt;`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) or `/me` – Represents the Facebook Page linked to your app user&#039;s Instagram professional account | [`/&lt;PAGE_ID&gt;`](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user) or `/me` – Represents the Facebook Page linked to your app user&#039;s Instagram professional account |
| **IDs** | The ID of your app user&#039;s Instagram professional account | The ID of the Facebook Page linked to your app user&#039;s Instagram professional account | The ID of the Facebook Page linked to your app user&#039;s Instagram professional account |
| **Basic Permission** | `instagram_business_basic` | `instagram_basic` | `instagram_basic` |
| **Field Specific Permissions** | Refer the [Instagram fields table](#fields) | Refer the [Instagram fields table](#fields) | Refer the [Instagram fields table](#fields) |

### Limitations

- Apps must be set to **Live** in the App Dashboard to receive webhook notifications.

- Advanced Access is required to receive `comments` and `live_comments` webhook notifications.

- The Instagram professional account that owns the media objects
[must be public to receive notifications for comments or &#064;mentions.](https://www.facebook.com/help/instagram/448523408565555)

- Notifications for Comments on
[Live media](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media)
are only sent during the live broadcast.

- Account level webhooks customization is not supported. If your app user is subscribed to any Instagram webhook field, your app receives notifications for all fields the app is subscribed to.

- Album IDs are not included in webhook notifications. Use the Comment ID received in the notification to get the album ID.

- The ad ID will not be returned for media used in dynamic ads.

- Notifications for `story_insights` events will only show metrics for the first 24 hours, before the story expires, even if the story is a highlight.

## Create an endpoint

This step must be completed before you can subscribe to any webhook fields in the App Dashboard.

Your endpoint must be able to process two types of HTTPS requests: [Verification Requests](#verification-requests) and [Event Notifications](#event-notifications). Since both requests use HTTPs, your server must have a valid TLS or SSL certificate correctly configured and installed. Self-signed certificates are not supported.

The sections below explain what will be in each type of request and how to respond to them. Alternatively, you can use our [sample app](https://developers.facebook.com/docs/graph-api/webhooks/sample-apps) which is already configured to process these requests.

### Verification Requests &#123;#verification-requests&#125;

Anytime you configure the Webhooks product in your App Dashboard, we&#039;ll send a `GET` request to your endpoint URL.  Verification requests include the following query string parameters, appended to the end of your endpoint URL. They will look something like this:

#### Sample Verification Request

```html
GET https://www.your-clever-domain-name.com/webhooks?
  hub.mode=subscribe&amp;
  hub.challenge=1158201444&amp;
  hub.verify_token=meatyhamhock
```

| Parameter | Sample Value | Description |
| --- | --- | --- |
| `hub.mode` | `subscribe` | This value will always be set to `subscribe`. |
| `hub.challenge` | `1158201444` | An `int` you must pass back to us. |
| `hub.verify_token` | `meatyhamhock` | A string that we grab from the **Verify Token** field in your app&#039;s App Dashboard. You will set this string when you complete the [Webhooks configuration settings](#the-steps) steps. |

**Note:** [PHP converts periods (.) to underscores (_) in parameter names](http://www.php.net/manual/en/language.variables.external.php).

#### Validating Verification Requests &#123;#validate-requests&#125;

Whenever your endpoint receives a verification request, it must:

* Verify that the `hub.verify_token` value matches the string you set in the **Verify Token** field when you [configure the Webhooks product](#the-steps) in your App Dashboard (you haven&#039;t set up this token string yet).
* Respond with the `hub.challenge` value.

If you are in your App Dashboard and configuring your Webhooks product (and thus, triggering a Verification Request), the dashboard will indicate if your endpoint validated the request correctly. If you are using the Graph API&#039;s [/app/subscriptions endpoint](https://developers.facebook.com/docs/graph-api/reference/app/subscriptions) to configure the Webhooks product, the API will indicate success or failure with a response.

### Event Notifications &#123;#event-notifications&#125;

When you configure your Webhooks product, you will subscribe to specific `fields` on an `object` type (e.g., the `photos` field on the `user` object). Whenever there&#039;s a change to one of these fields, we will send your endpoint a `POST` request with a JSON payload describing the change.

For example, if you subscribed to the `user` object&#039;s `photos` field and one of your app&#039;s Users posted a Photo, we would send you a `POST` request that would look something like this:

```html
POST / HTTPS/1.1
Host: your-clever-domain-name.com/webhooks
Content-Type: application/json
X-Hub-Signature-256: sha256=&#123;super-long-SHA256-signature&#125;
Content-Length: 311

&#123;
  &quot;entry&quot;: [
    &#123;
      &quot;time&quot;: 1520383571,
      &quot;changes&quot;: [
        &#123;
          &quot;field&quot;: &quot;photos&quot;,
          &quot;value&quot;:
            &#123;
              &quot;verb&quot;: &quot;update&quot;,
              &quot;object_id&quot;: &quot;10211885744794461&quot;
            &#125;
        &#125;
      ],
      &quot;id&quot;: &quot;10210299214172187&quot;,
      &quot;uid&quot;: &quot;10210299214172187&quot;
    &#125;
  ],
  &quot;object&quot;: &quot;user&quot;
&#125;
```

#### Payload Contents

Payloads will contain an object describing the change. When you [configure the webhooks product](#the-steps), you can indicate if payloads should only contain the names of changed fields, or if payloads should include the new values as well.

We format all payloads with JSON, so you can parse the payload using common JSON parsing methods or packages.

**Warning:** You will not be able to query historical webhook event notification data, so be sure to capture and store any webhook payload content that you want to keep.

Most payloads will contain the following common properties, but the contents and structure of each payload varies depending on the object fields you are subscribed to. Refer to each object&#039;s [reference](https://developers.facebook.com/docs/graph-api/webhooks/reference) document to see which fields will be included.

| Property | Description | Type |
| --- | --- | --- |
| `object` | The object&#039;s type (e.g., `user`, `page`, etc.) | `string` |
| `entry` | An array containing an object describing the changes. Multiple changes from different objects that are of the same type may be batched together. | `array` |
| `id` | The object&#039;s ID | `string` |
| `changed_fields` | An array of strings indicating the names of the fields that have been changed. Only included if you *disable* the **Include Values** setting when configuring the Webhooks product in your app&#039;s App Dashboard. | `array` |
| `changes` | An array containing an object describing the changed fields and their new values. Only included if you *enable* the **Include Values** setting when configuring the Webhooks product in your app&#039;s App Dashboard. | `array` |
| `time` | A UNIX timestamp indicating when the Event Notification was sent (not when the change that triggered the notification occurred). | `int` |

#### Validating Payloads &#123;#validate-payloads&#125;

We sign all Event Notification payloads with a **SHA256** signature and include the signature in the request&#039;s `X-Hub-Signature-256` header, preceded with `sha256=`. You don&#039;t have to validate the payload, but you should.

To validate the payload:

1. Generate a **SHA256** signature using the payload and your app&#039;s **App Secret**.
1. Compare your signature to the signature in the `X-Hub-Signature-256` header (everything after `sha256=`). If the signatures match, the payload is genuine.

#### Responding to Event Notifications

Your endpoint should respond to all Event Notifications with `200 OK HTTPS`.

#### Frequency

Event Notifications are aggregated and sent in a batch with a **maximum** of 1000 updates. However batching cannot be guaranteed so be sure to adjust your servers to handle each Webhook individually.

If any update sent to your server fails, we will retry immediately, then try a few more times with decreasing frequency over the next 36 hours. Your server should handle deduplication in these cases. Unacknowledged responses will be dropped after 36 hours.

Note: The frequency with which Messenger event notifications are sent is different. Please refer to the [Messenger Platform Webhooks documentation](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks) for more information.

## Enable Subscriptions

Your app must enable subscriptions by sending a `POST` request to the `/me/subscribed_apps` endpoint with the `subscribed_fields` parameter set to a comma-separated list of webhooks fields.

#### Request Syntax

_Formatted for readability._

```http
POST /me/subscribed_apps
  ?subscribed_fields=&lt;LIST_OF_WEBHOOK_FIELDS&gt;
  &amp;&lt;ACCESS_TOKEN&gt;
```

#### Request Parameters

| Value Placeholder | Value Description |
| --- | --- |
| `/me` | Represents your app user&#039;s Instagram professional account ID or the Facebook Page ID that is linked to your app user&#039;s Instagram professional account |
| `&lt;ACCESS_TOKEN&gt;` | App user&#039;s Instagram User access token or Facebook Page access token. |
| `&lt;LIST_OF_WEBHOOK_FIELDS&gt;` | A comma-separated list of webhook fields that your app is subscribed to. |

#### Example Request

_Formatted for readability._

```curl
curl -i -X POST \
  &quot;https://graph.instagram.com/v25.0/1755847768034402/subscribed_apps
  ?subscribed_fields=comments,messages
  &amp;access_token=EAAFB...&quot;
```

On success, your app receives a JSON response with `success` set to `true`.

```json
&#123;
  &quot;success&quot;: true
&#125;
```

## Subscribe to webhook fields &#123;#fields&#125;

You can subscribe to the following fields to receive notifications for events that take place on Instagram.

| Instagram Webhook field | Instagram API setup with Instagram Login permissions | Instagram API setup with Facebook Login permissions | Instagram Messaging API&lt;br&gt;(Messenger Platform) permissions |
| --- | --- | --- | --- |
| `comments` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_comments` | * `instagram_basic`&lt;br&gt;* `instagram_manage_comments`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` | x |
| `live_comments` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_comments` | * `instagram_basic`&lt;br&gt;* `instagram_manage_comments`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` | x |
| `mentions` | Included in the `comments` webhook notification | * `instagram_basic`&lt;br&gt;* `instagram_manage_comments`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` | x |
| `message_echoes` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_comments` | x | Included in the `messages` webhook notification |
| `message_reactions` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages` | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_messages`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` |
| `messages` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages` | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_messages`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` |
| `messaging_handover` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages` | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_messages`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` |
| `messaging_optins` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages` | x | x |
| `messaging_policy_enforcement` | x | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_messages`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` |
| `messaging_postbacks` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages` | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_messages`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` |
| `messaging_referral` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages` | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_messages`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` |
| `messaging_seen` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages` | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_messages`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` |
| `response_feedback` | x | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_messages`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` |
| `standby` | * `instagram_business_basic`&lt;br&gt;* `instagram_business_manage_messages` | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_messages`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` |
| `story_insights` | x | * `instagram_basic`&lt;br&gt;* `instagram_manage_insights`&lt;br&gt;* `pages_manage_metadata`&lt;br&gt;* `pages_read_engagement`&lt;br&gt;* `pages_show_list` | x |

## mTLS for Webhooks

Mutual TLS (mTLS) is a method for mutual authentication.

mTLS ensures that the parties at each end of a network connection are who they claim to be by verifying that they both have the correct private key. The information within their respective TLS certificates provides additional verification.

### How to configure mTLS

Once you enable mTLS on your subscription to WhatsApp Business Account, Meta will present a client certificate together with its signing intermediate certificate. Both certificates are used to create a TLS handshake of Webhook requests to your server. Your server then can verify the sender’s identity of these requests by the trust chain and the common name (CN).

The client certificate is signed by a Meta-owned Certificate Authority (CA). Configure your server or load balancer to trust the Meta outbound API CA certificate (meta-outbound-api-ca-2025-12.pem). This certificate replaces the previous DigiCert-signed certificate, which expired on April 15, 2026.  

### Client Certificate Verification

After setting up HTTPS for receiving Webhook requests, complete the following steps to verify the client certificate and its common name `client.webhooks.fbclientcerts.com`:

1. Install the Meta outbound API CA certificate  
1. Verify the client certificate against the CA certificate
1. Verify the common name (client.webhooks.fbclientcerts.com) of the client certificate  

Note: Servers receiving Webhooks must be using HTTPS; and we are always verifying the certificate from your HTTPS server for security.

### Example

Depending on your server’s setup, the above steps vary in details. We illustrate by two examples, one for Nginx and one for AWS Application Load Balancer (ALB).

### Nginx

1. Download the Meta outbound API CA certificate (meta-outbound-api-ca-2025-12.pem) to your server, for example to `/etc/ssl/certs/meta-outbound-api-ca-2025-12.pem`

1. Turn on mTLS by Nginx directives
```
ssl_verify_client          on;
ssl_client_certificate     /etc/ssl/certs/meta-outbound-api-ca-2025-12.pem;
ssl_verify_depth           3;
```

3. Verify the CN from Nginx embedded variable `$ssl_client_s_dn` equals `&quot;client.webhooks.fbclientcerts.com&quot;` (
```
if ($ssl_client_s_dn ~ &quot;CN=client.webhooks.fbclientcerts.com&quot;) &#123;
        return 200 &quot;$ssl_client_s_dn&quot;;
&#125;
```

### AWS Application Load Balancer (ALB)

1. Download the Meta outbound API CA certificate (meta-outbound-api-ca-2025-12.pem) to an S3 bucket.
1. Configure the HTTPS listener on the ALB to enable mTLS with the trust store containing the Meta CA certificate in the S3 bucket.
1. In your application code, extract the CN from the HTTP header [&quot;X-Amzn-Mtls-Clientcert-Subject&quot;](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/mutual-authentication.html), and verify it equals                      `&quot;client.webhooks.fbclientcerts.com&quot;`.

### Downloadable CA certificate  

meta-outbound-api-ca-2025-12.pem

## Test setup

1. Send your Instagram professional account a test message (the public account added in the Meta App Dashboard for testing). This should trigger a `messages` webhook event. The notification should contain the `recipient.id`, set to your Instagram professional account&#039;s Instagram-scoped ID, and the `is_echo` and `is_self` properties, both set to `true`, within the `messaging` array.
2. Send a response to your Instagram-scoped ID using the API.

## Next steps

Learn how to [send and receive messages from Instagram professional accounts](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api)

## See also

- [Webhooks from Meta | Developer Documentation](https://developers.facebook.com/docs/graph-api/webhooks)

