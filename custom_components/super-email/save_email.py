import imaplib


def save_email(host, port, username, password, folder, filename):
    gmail = imaplib.IMAP4_SSL(host, port=port)
    gmail.login(username, password)
    gmail.select(folder)
    typ, data = gmail.search(None, "ALL")

    d = data[0].split()

    e = d[len(d) - 1]

    typ, data = gmail.fetch(e, "(RFC822)")
    f = open("%s/%s" % ("config/uber", filename), "wb")
    f.write(data[0][1])
    gmail.close()
    gmail.logout()
