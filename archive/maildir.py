import datetime
import mailbox

from jmap.modules.mail import EmailModule
from jmap.models.models import MailboxGetArgs, MailboxGetResponse, Mailbox, EmailQueryArgs, EmailQueryResponse, \
    EmailGetArgs, EmailGetResponse, ThreadGetArgs, ThreadGetResponse


class MailboxEmailModule(EmailModule):
    """
    Works on top of the traditional mailbox format.
    """


class MboxModule(EmailModule):
    """This serves JMAP email from a particular mbox file.

    - mbox is just a bunch of emails one after another. To even read the mails,
      you have to load the whole file into memory. To store data such as "read
      flags", you have to add X-headers to the emails in the file. This requires
      rewriting all subsequent emails, unless you use tricks such as pre-kept space,
      like dovecot does. To store information such as "next free message id", dovecot
      insert special X-headers into the very first message of the mbox. Stuff like
      that. Those are essentially app-specific extensions.

    - So our implementation is either going to parse emails for every request, using
      no indices, working directly with the list of mails in memory, do don't touch
      the mailbox file, generate message ids on every request based on the mail content,
      and be super slow.

    - Does that, but speed things up using an in-memory index that is rebuild on opening
      the file (doesn't hurt).

    - Have our own index format on disk, and store our own state (such as msg ids)
      inside custom headers (or outside). May or may not work together with other
      tools accessing the mailbox.

    - Match an existing implementation such as dovecot and read and work with their
      index files.

    The python mbox module doesn't actually help us a lot here, because it always reads
    the whole file into memory. Certain performance gains that indices might give us
    would require a custom implementation.

    It really depends on what we want. Do we want to work along side an existing email
    server, adding JMAP capability on top? Do we want to be our own server?

    Related links:

    - https://wiki.dovecot.org/Design/Indexes/MailIndexApi
    """

    def __init__(self, mbox_file, **kwargs):
        self.mbox = mailbox.mbox(mbox_file)
        super().__init__(**kwargs)

    def get_state_for(self, type: str):
        return len(self.mbox)

    def handle_mailbox_get(self, context, args: MailboxGetArgs):
        # mbox does not support folders itself, so we just pretend there is a single one.
        return MailboxGetResponse(
            account_id=args.account_id,
            state=self.get_state_for(Mailbox),
            list=[
                Mailbox(
                    id='default',
                    name="Mail",
                    role="inbox"
                )
            ],
            not_found=[]
        )

    def handle_email_query(self, context, args: EmailQueryArgs) -> EmailQueryResponse:
        """Return ids of emails that match the given filters.
        """

        filtered = self.mbox.items()
        result = filtered[args.position:args.limit]
        # TODO: Apply the sort

        return EmailQueryResponse(
            account_id=args.account_id,
            collapse_threads=args.collapse_threads,
            filter=args.filter,
            #sort=args.sort,
            total=1000,
            query_state='none',
            position=0,
            ids=[x[0] for x in result],
            can_calculate_changes=False, # TODO: We probably can
        )

    def handle_email_get(self, context, args: EmailGetArgs) -> EmailGetResponse:
        """
        Query the given emails.
        """
        if not args.ids:
            matching = self.mbox.items()
        else:
            matching = filter(lambda x: str(x[0]) in args.ids, self.mbox.items())

        return EmailGetResponse(
            account_id=args.account_id,
            state=self.get_state_for(Mailbox),
            list=[
                python_message_to_jmap_message(message, id=id, query_thread='threadId' in args.properties)
                for id, message in matching
            ],
            not_found=[]
        )

    def handle_thread_get(self, context, args: ThreadGetArgs) -> ThreadGetResponse:
        if not args.ids:
            matching = self.mbox.items()
        else:
            matching = filter(lambda x: str(x[0]) in args.ids, self.mbox.items())

        return ThreadGetResponse(
            account_id=args.account_id,
            state=self.get_state_for(Mailbox),
            list=[
                dict(
                    id='k' +str(id),
                    emailIds=[str(id)],
                    accountId='default'
                )
                for id, m in matching
            ],
            not_found=[]
        )


def python_message_to_jmap_message(pymsg, id, query_thread):
    if query_thread or True:
        result = {
            "id": str(id),
            "threadId": str(id),
            'mailboxIds': {'default': True},
            "keywords": {
                "$Seen": True,
            },
            "hasAttachment": True,
            "receivedAt": datetime.datetime.utcnow(),
            "subject": 'ById: Opera Mail: slick, stylish, sophisticated',
            "from": [{"name": 'ACME Staff', "email": 'nmjenkins@facebook.com'}],
            "to": [{"name": 'A.N. Other', "email": 'jimmy@jimjim.ja'},
                   {"name": 'Imogen Jones', "email": 'immy@jones.com'}],
            "size": 100,
            'preview': 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim adminim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur.'
        }
        return result

    else:
        result = {
            "id": str(id),
            "blobId": 'http://messages/' + str(id),
            "cc": None,
            "bcc": None,
            "replyTo": [{
                "name": 'Neil Jenkins',
                "email": 'neil@replyto.com'
            }],
            "attachments": [],
            "sentAt": datetime.datetime.utcnow(),
            "htmlBody": """<div>asdfasdf<br></div><div>a<br></div><div>sdfasdf<br></div><div><br></div><div>asdf<br></div><div>asdf<br></div><div><br></div><div>asdf</div><div><br></div><div>On Fri, 20 Jan 2012, at 06:14 AM, Marian Hackett wrote:<br></div><blockquote><div><br></div><div><a href=\"https://bugs.opera.com/browse/IRIS-1199 target=\" defang__top\"=\"\" target=\"_blank\">https://bugs.opera.com/browse/IRIS-1199</a target=\"_blank\"><br></div><div><br></div><div><br></div><div>Marian Hackett updated IRIS-1199:<br></div><div>---------------------------------<br></div><div><br></div><div> &nbsp; Priority": P3&nbsp; (was: \u2014)<br></div><div> &nbsp; &nbsp; &nbsp; &nbsp; CC": [johan, marianh, neilj, rjlov, robm]<br></div><div><br></div><div><br></div><div><br></div><div>-- <br></div><div>This message is automatically generated by JIRA.<br></div><div><br></div><div><br></div><div><br></div></blockquote>\n""",
            "textBody": """On Mon, 14 Mar 2011 13:58:04 +0100, Peter Krefting <peter@opera.com> wrote:\n\n> Conrad Newton <conrad.newton@opera.com>:\n>\n>> the only special item you have to watch out for is the deduction for  \n>> being a foreigner. This deduction is relevant only during your first  \n>> two years in Norway, and it will save you some money.\n>\n> Is it only two years now? Then someone should update  \n> https://wiki.oslo.osa/staffwiki/ExPats/Tax\n>\n\n\"This page was last modified on 12 October 2005, at 11:26.\"\n\nYes, it's been 2 years ever since 2006, in that case, since when I started  \nit was :) 2 years ;) and has stayed the same since. :) ;)\n\nThere's an email address here:\n\nblah@blah.com\n\nAnd a url with space:\n\n<http://somewhere.com/a url\"with spaces.txt>\n\nA regular url here": http://somewhere.com\n\n> Some indented\n> text here\n\nAnd *this* should be bold and _this_ should be underlined\n\nThis is an FTP link"": ftp://foo.example.com.\n\nWhat about _this_and_this_ which should all be underlined, and *all*of*this* should be bold\n\n\n-- \nDevil May Care\n_______________________________________________\nEx-pats mailing list\nEx-pats@list.opera.com\nhttps://list.opera.com/mailman/listinfo/ex-pats\n\n""",
        }
        return result