# User Profile API



The User Profile API allows you to use an Instagram Scoped ID (IGSID) to retrieve customer profile information. You can use this information to create a personalized experience for people interacting with your business.

## User consent

**User consent is required to access the user profile.** A person sets user consent only when they send a message to your business, or click icebreakers or persistent menu. If a person comments on a post or comment but has not sent a message to a business, your app receives an error, **User consent is required to access the user profile.**

### Requirements

You need:

* The `instagram_basic` permission
* The `instagram_manage_messages` permission
* The `pages_manage_metadata` permission
* The `pages_read_engagement` permission
* The `pages_show_list` permission
* A Page access token requested by a person who can perform the `MODERATE` task on the Page

### Limitations

If a customer has blocked your business, you can&#039;t view their information.

## User profile fields

The following profile fields are available for all Graph API versions.

| Field Name | Description |
| --- | --- |
| `name`&lt;br&gt;&lt;br&gt;_string_ | The customer&#039;s name (can be null if name not set) |
| `profile_pic`&lt;br&gt;&lt;br&gt;_url_ | The URL for the customer&#039;s profile picture (can be null if profile pic not set). The URL expires after a few days. |
| `is_verified_user`&lt;br&gt;&lt;br&gt;_boolean_ | Verification status for the customer |
| `follower_count`&lt;br&gt;&lt;br&gt;_int_ | Follower count for the customer |
| `is_user_follow_business`&lt;br&gt;&lt;br&gt;_boolean_ | Indicates whether the customer follows the business or not |
| `is_business_follow_user`&lt;br&gt;&lt;br&gt;_boolean_ | Indicates whether the business follows the customer or not |
| `username`&lt;br&gt;&lt;br&gt;_string_ | The username for the customer&#039;s Instagram account |

### Sample request

To get a customer&#039;s profile information, send a `GET` request to the Instagram Scoped ID node for the customer and include the fields you want to view.

_Formatted for readability._

```curl
curl -X GET &quot;https://graph.facebook.com/v25.0/&lt;INSTAGRAM_SCOPED_USER_ID&gt;
  ?fields=name,username,profile_pic,follower_count,is_user_follow_business,is_business_follow_user
  &amp;access_token=&lt;PAGE_ACCESS_TOKEN&gt;&quot;
```

On success, your app receives the following JSON response:

```json
&#123;
  &quot;name&quot;: &quot;Peter Chang&quot;,
  &quot;username&quot;: &quot;peter_chang_live&quot;,
  &quot;profile_pic&quot;: &quot;https://fbcdn-profile-...&quot;,
  &quot;follower_count&quot;: 1234
  &quot;is_user_follow_business&quot;: false,
  &quot;is_business_follow_user&quot;: true,
&#125;
```

### Developer Support

* Use the  [Meta Status tool](https://metastatus.com) to check for the status and outages of Meta business products.
* Use the [Meta Developer Support tool](https://developers.facebook.com/support) to report bugs and view reported bugs, get help with Ads or Business Manager, and more.

