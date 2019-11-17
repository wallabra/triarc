import praw
import re
import random
import time
import sys
import sqlite3 as sqlite
import os
import queue
import snobeconfig as CFG


from cobe.brain import Brain



class Snobe(object):
    def __init__(self, brain_file, **kwargs):
        self.reddit = praw.Reddit(**kwargs)
        self.conn = sqlite.connect('snobe.db')
        self.brain = Brain(brain_file)

        self.reply_queue = queue.Queue()
        self.last_reply = None
        self.reply_interval = 8
        
        c = self.sql()
        c.execute('CREATE TABLE IF NOT EXISTS LearnedComments (subm_id STRING, comm_id STRING);')
        c.execute('CREATE TABLE IF NOT EXISTS CheckedComments (subm_id STRING, comm_id STRING, reply STRING);')
        self.sql_save()

    def step(self):
        if not self.reply_queue.empty() and (not self.last_reply or time.time() - self.last_reply >= self.reply_interval):
            self.last_reply = time.time()
            self._reply(*self.reply_queue.get())

    def _reply(self, model, reply):
        if isinstance(model, praw.models.Comment):
            c = self.sql()
            c.execute('INSERT INTO CheckedComments VALUES (?, ?, ?);', (model.submission.id, model.id, reply))
            self.sql_save()
        
        res = model.reply(re.sub(r'(?<=\W)/?u/[^\W]+(?=\W)', '<anonymous person>', reply) + '\n\n    *Beep boop. I\'m a bot!* If something goes wrong, please tell {}...'.format(CFG))
            
        print("- Sent reply to {}".format(model.id))
        
        return res

    def sql(self):
        return self.conn.cursor()
    
    def sql_save(self):
        self.conn.commit()
    
    def check_learn(self, *submissions):
        c = self.sql()
        
        for submission in submissions:
            submission.comments.replace_more(limit=0)
            them = len(submission.comments.list())
            
            for i, comment in enumerate(submission.comments):
                c.execute('SELECT * FROM LearnedComments WHERE subm_id = ? AND comm_id = ?;', (submission.id, comment.id))
                
                if not c.fetchone():
                    self.learn(comment)
                    
                    print("- Learned from {} ({}/{})".format(comment.id, i + 1, them))
                    print(comment.body)
                    print()
                    
                    c.execute('INSERT INTO LearnedComments VALUES (?, ?);', (submission.id, comment.id))
                    
        self.sql_save()
                
    def check_reply(self, *submissions):
        c = self.sql()
        
        for submission in submissions:
            submission.comments.replace_more(limit=0)
            them = len(submission.comments.list())
            
            for i, comment in enumerate(submission.comments):
                c.execute('SELECT * FROM CheckedComments WHERE subm_id = ? AND comm_id = ?;', (submission.id, comment.id))
                
                if not c.fetchone():
                    rep = self.reply(comment)
                    
                    print("- Composed reply to {} ({}/{})".format(comment.id, i + 1, them))
                    print(rep)
                    print()
                    
                else:
                    print("# Ignored " + comment.id)
                
    def reply_thread(self, *submissions):
        c = self.sql()
        
        for submission in submissions:
            body = []
            submission.comments.replace_more(limit=0)
            them = len(submission.comments.list())
            
            for i, comment in enumerate(submission.comments):
                c.execute('SELECT * FROM CheckedComments WHERE subm_id = ? AND comm_id = ?;', (submission.id, comment.id))
                
                if not c.fetchone():
                    rep = self.get_reply(comment)
                    
                    print("- Composed simulated reply from {} ({}/{})".format(comment.id, i + 1, them))
                    print(rep)
                    print()
                    
                    body.append(rep)
                    
                else:
                    print("# Ignored " + comment.id)
                    
            print()
            
            reply = random.choice(body)
            print('Selected reply:', reply)
            
            self.reply_queue.put((submission, reply))
                
    def check(self, *submissions):
        self.check_learn(*submissions)
        self.check_reply(*submissions)
        
    def reply(self, comment):
        reply = self.get_reply(comment)

        self.reply_queue.put((comment, reply))
        
        return reply
    
    def learn(self, comment):
        self.brain.learn(comment.body)
        
    def get_reply(self, comment, loop_ms=200):
        print("* Composing reply to:")
        print(comment.body)
        print()
        
        return self.brain.reply(comment.body, loop_ms=loop_ms)
                
    def send_until_done(self):
        print("5...")
        time.sleep(1)
        print("4...")
        time.sleep(1)
        print("3...")
        time.sleep(1)
        print("2...")
        time.sleep(1)
        print("1...")
        time.sleep(1)
        
        while not self.reply_queue.empty():
            self.step()
            time.sleep(1)


def main():
    if len(sys.argv) <= 2:
        print('Provide either "learn", "reply", "learn-many" or "reply-all" as a command, and a list of Reddit submission URLs to either just learn from, or learn and reply.')
        return False
    
    snobe = Snobe(os.environ.get('BRAIN', 'brains/reddit.brain'), client_id=CFG.client_id, client_secret=CFG.client_secret, password=CFG.password, user_agent=CFG.user_agent, username=CFG.username)
    
    args = sys.argv[1:]
    command = args.pop(0)
    
    if command == 'learn':
        snobe.check_learn(*list(snobe.reddit.submission(url=sub) for sub in args))
        
    elif command == 'reply-all':
        snobe.check(*list(snobe.reddit.submission(url=sub) for sub in args))
        
        snobe.send_until_done()
        
    elif command == 'test-replies':
        snobe.check_learn(*list(snobe.reddit.submission(url=sub) for sub in args))
        snobe.reply_thread(*list(snobe.reddit.submission(url=sub) for sub in args))
        
    elif command == 'reply':
        snobe.check_learn(*list(snobe.reddit.submission(url=sub) for sub in args))
        snobe.reply_thread(*list(snobe.reddit.submission(url=sub) for sub in args))
        
        snobe.send_until_done()
        
    elif command == 'learn-many':
        if len(args) < 2 or not args[1].isdigit():
            print("\"learn-many\" requires a subeddit name and a number of posts to read, and noindividual links.")
            return False
        
        how_many = int(args[1])
        
        snobe.check_learn(*list(snobe.reddit.subreddit(args[0]).hot(limit=how_many)))
    
    else:
        print('The command must be either "learn", "reply" or "reply-all".')
        return False
    
    return True
    
if __name__ == '__main__':
        main()
