# Sample Instagram Experience



Original Coast Clothing is a fictional clothing brand created to showcase the key features of the Instagram Platform. Using this demo as inspiration, anyone can create a Messenger API support for Instagram experience that leverages both automation and live customer support. [Open-source code](https://github.com/fbsamples/original-coast-clothing-ig) for the app and a guide on how to deploy the experience on your local environment or remote server are provided.

Try it now by messaging **[&#064;originalcoastclothing](http://instagram.com/originalcoastclothing?ref=DEVDOCS)** or **[commenting on a post](https://www.instagram.com/p/CNaLh5xgppt/)**.

## Platform features &#123;#platform_features&#125;

This experience leverages the following platform features. If you decide to [deploy the experience](#deploy) on your Page, the code will use them all:

* [Messaging](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/send-message)
    * Text, Image, and link previews
    * Generic templates
* [Webhooks](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks)
* [Quick Replies](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/quick-replies)
* [User Profiles](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/user-profile)
* [Private Replies](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/private-replies)
* [Ice Breakers](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/ice-breakers)

## Deploy this experience on Instagram &#123;#deploy&#125;

By the end of this guide, you&#039;ll have a full Instagram app running on your server, answering messages from your account.

The code that powers this experience is open-source. Anyone can get started with developing a messaging experience.

The code is released under the BSD License, allowing you to use it freely for your needs. The code is hosted on [GitHub](https://github.com/fbsamples/original-coast-clothing-ig) for further reference.

### Requirements to deploy an Instagram app &#123;#requirements&#125;

- An **[Instagram Professional Account](https://www.facebook.com/help/instagram/138925576505882)** (either Creator or Business account).
- A **Facebook Page** [connected to that Instagram account](https://developers.facebook.com/docs/instagram-api/overview#pages). Make sure that you have a Facebook Page that represents your Instagram Professional account identity when connecting with users. To create a new Page, visit [https://www.facebook.com/pages/create](https://www.facebook.com/pages/create), you can also set up a test Page to start.
- A **Developer Account** that can perform [Tasks](https://developers.facebook.com/docs/instagram-api/overview#tasks) on your Page. A Developer Account allows you to create new apps, which are the core of any Facebook integration. You can register as a developer by going to the [Facebook Developers website](https://developers.facebook.com/) and clicking the &quot;Get Started&quot; button.
- A **[Facebook app](https://developers.facebook.com/docs/development/create-an-app)** with Basic settings configured. To create a new app, visit [https://developers.facebook.com/](https://developers.facebook.com/) and click on **Add New App**.

#### Setup steps &#123;#setup&#125;

The objective of this section is to gather all the access tokens and ids necessary for the Instagram app to successfully send and receive messages. Before you begin, make sure you have completed all of the requirements listed above. At this point you should have a Page, a registered Facebook app, and an Instagram Professional account.

If you just created a new Facebook app, it is probably in **development mode**. Note that apps in this mode are only allowed to message people connected to the app (Admins, Developers, and Testers). You can continue with this guide in this mode, but once your app is ready to be public, the app needs to go through app review for the [`instagram_manage_messages`](https://developers.facebook.com/docs/permissions/reference/instagram_manage_messages) permission. For more info, see [App Review](https://developers.facebook.com/docs/apps/review)

1. Configure your Instagram integration by following the [Getting Started](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/get-started) documentation.
2. Add some Instagram test accounts that you&#039;ll use to test the experience.

At this point you should have the following:

- App ID
- App Secret
- Page ID
- Page Access Token
- Instagram Account connected to Page
- Instagram Account(s) registered as test accounts

## Installation &#123;#installation&#125;

You will need:

- [Node](https://nodejs.org/en/) 10.x or higher
- A server for your code. Options include:
    - Local tunneling service such as [ngrok](https://ngrok.com/)
    - Remote server service such as [Heroku](https://www.heroku.com/) or [Glitch](http://glitch.com/)
    - Your own web server

### One-click deploy using Heroku or Glitch &#123;#one-click&#125;

The experience can be automatically deployed to Heroku or Glitch using the following buttons. You will be prompted to enter the needed environment variables to complete the setup.

[Deploy on Heroku](https://bit.ly/3vU744Q)

[Deploy on Glitch](https://bit.ly/3wB07G1)

### Deploy locally using ngrok &#123;#ngrok&#125;

A tunneling service exposes your local web server to an external URL that can be reached by Facebook webhooks. There are many such services. In this example, you will use ngrok.

**1. Clone the repo**

Clone the repository to your local machine:

```bash
git clone https://github.com/fbsamples/original-coast-clothing-ig.git
cd original-coast-clothing-ig
```

**2. Install tunneling service**

If not already installed, install ngrok via [download](https://ngrok.com/download) or via command line:

```bash
$ npm install -g ngrok
```

In the directory of this repo, request a tunnel to your local server with your preferred port
```bash
$ ngrok http 3000
```

The screen should show the ngrok status:

```bash
Session Status                online
Account                       Redacted (Plan:iuluufkccebegkhifrlgfhudrtbthgln Free)
Version                       2.3.35
Region                        United States (us)
Web Interface                 http://127.0.0.1:4040
Forwarding                    http://1c3b838deacb.ngrok.io -&gt; http://localhost:3000
Forwarding                    https://1c3b838deacb.ngrok.io -&gt; http://localhost:3000
```

Note the https URL of the external server that is forwarded to your local machine. In the above example, it is `https://1c3b838deacb.ngrok.io`.

**3. Install the dependencies**

Open a new terminal tab, also in the repo directory.

```bash
$ npm install
```

Alternatively, you can use [Yarn](https://yarnpkg.com/en/):

```bash
$ yarn install
```

**4. Set up .env file**

Copy the file `.sample.env` to `.env`

```bash
$ cp .sample.env .env
```

Edit the `.env` file to add all the values for your app and page.

**5. Run your app locally**

```bash
$ node app.js
```

You should now be able to access the default page of the application in your browser at [http://localhost:3000](http://localhost:3000)

Confirm that you can also access the application at the external URL from step 2.

### Deploy using Heroku &#123;#heroku&#125;

**1. Clone the repo**

Clone the repository to your local machine:

```bash
git clone https://github.com/fbsamples/original-coast-clothing-ig.git
cd original-coast-clothing-ig
```

**2. Install the Heroku CLI**

If the directory is not already a git repo, create one:

```bash
$ git init
Initialized empty Git repository in .git/
$ git add .
$ git commit -m &quot;My first commit&quot;
```

**3. Install the Heroku CLI**

If not already installed, download and install the [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli)

**4. Create an app from the CLI**

```bash
$ heroku apps:create

Creating app... done, ⬢ mystic-wind-83
Created http://mystic-wind-83.herokuapp.com/ | git&#064;heroku.com:mystic-wind-83.git
```

Note the name given to your app. In this example, it was `mystic-wind-83`.

**5. Set your environment variables**

On the [Heroku App Dashboard](https://dashboard.heroku.com/), find your app and set up the config vars following the comments in the file `.sample.env`

Alternatively, you can set env variables from the command line like this:

```bash
$ heroku config:set PAGE_ID=XXXX
```

**6. Deploy the code**

```bash
$ git push heroku master
```

**7. View log output**

```bash
$ heroku logs --tail
```

### Connect your webhook &#123;#webhook&#125;

Now that your server is running, your webhook endpoint is at the path `/webhook`. In the Heroku example above, this would be `http://mystic-wind-83.herokuapp.com/webhook`.

Set up your webhook by following the [Messenger Platform Webhooks guide](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks).

After the webhook subscription is validated, subscribe to the following events:

- comments
- messages
- `messaging_postbacks`

Test the webhooks by clicking the &quot;Test&quot; buttons next to the subscribed events. You should see the test events in the log output of your server.

### Test that your app setup is successful &#123;#test&#125;

While logged in to an account with the role of &quot;Instagram Tester&quot;, try sending a message to the Instagram account connected to your Page, or leaving a comment on a post.

If you see a response to your message in Instagram, you have fully set up your app.

### Troubleshooting &#123;#troubleshooting&#125;

#### The app only replies to me, but not someone else &#123;#app_in_dev_mode&#125;
The Facebook app is likely still in Development Mode. You can add someone as a tester of the app, if they accept, the app will be able to message them. Once ready, you may request the `instagram_manage_messages` permission to be able to reply to anyone.

#### Other issues &#123;#issues&#125;

Is this guide wrong? [Let us know by filing an Issue](https://github.com/fbsamples/original-coast-clothing/issues)
