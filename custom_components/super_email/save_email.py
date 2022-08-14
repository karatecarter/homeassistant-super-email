import imaplib


def save_email(host, port, username, password, emailfolder, savefolder, filename):
    """Save the latest email to a file"""
    imap = imaplib.IMAP4_SSL(host, port=port)
    imap.login(username, password)
    imap.select(emailfolder)
    typ, data = imap.search(None, "ALL")  # pylint: disable=unused-variable

    d = data[0].split()

    e = d[len(d) - 1]

    typ, data = imap.fetch(e, "(RFC822)")
    file = open("%s/%s" % (savefolder, filename), "wb")
    file.write(data[0][1])
    file.close()
    imap.close()
    imap.logout()
