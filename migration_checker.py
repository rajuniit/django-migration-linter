from __future__ import print_function
import argparse
import os
import re
from subprocess import Popen, PIPE


class MigrationChecker:
    MIGRATION_FOLDER_NAME = 'migrations'

    migration_tests = (
        {
            'fn': lambda sql: re.search('NOT NULL', sql),
            'err_msg': 'NOT NULL constraint on columns'
        }, {
            'fn': lambda sql: re.search('DROP COLUMN', sql),
            'err_msg': 'DROPPING columns'
        }, {
            'fn': lambda sql: re.search('ADD COLUMN .* DEFAULT', sql),
            'err_msg': 'ADD columns with default'
        }
    )

    def __init__(self, django_folder, commit_id=None):
        self.location = django_folder
        self.commit_id = commit_id
        self.changed_migration_files = []
        self._gather_migrations()

    def _gather_migrations(self):
        # Find (one of) the initial commits
        if not self.commit_id:
            git_init_cmd = 'cd {0} && git rev-list HEAD | tail -n 1'.format(self.location)
            process = Popen(git_init_cmd, shell=True, stdout=PIPE, stderr=PIPE)
            for line in process.stdout.readlines():
                self.commit_id = line.strip()
                break
            process.wait()

        # Get changes since specified commit
        git_diff_command = 'cd {0} && git diff --name-only {1}'.format(self.location, self.commit_id)
        diff_process = Popen(git_diff_command, shell=True, stdout=PIPE, stderr=PIPE)
        for line in diff_process.stdout.readlines():
            # Only gather lines that include migrations
            if self.MIGRATION_FOLDER_NAME in line:
                self.changed_migration_files.append(line.strip())
        diff_process.wait()
        if diff_process.returncode != 0:
            raise Exception('Error while executing git diff command')

    def check_migrations(self):
        nb_valid = 0
        nb_erroneous = 0
        for migration in self.changed_migration_files:
            app_name, migration_name = self._split_migration_path(migration)
            sql_statements = self.django_sqlmigrate(app_name, migration_name)
            print('{0}... '.format(migration), end='')

            errors = set()
            for statement in sql_statements:
                is_valid, err_msg = self._test_sql_statement_for_backward_incompatibility(statement)
                if not is_valid:
                    errors.add(err_msg)
            if not errors:
                print('OK')
                nb_valid += 1
            else:
                print('ERR')
                nb_erroneous += 1
                for err in errors:
                    print('\t' + err)
        print('*** Summary:')
        print('Valid migrations: {0}/{1} - erroneous migrations: {2}/{1}'.format(nb_valid, len(self.changed_migration_files), nb_erroneous))

    def _split_migration_path(self, migration_path):
        decomposed_path = split_path(migration_path)
        for i, p in enumerate(decomposed_path):
            if p == self.MIGRATION_FOLDER_NAME:
                return decomposed_path[i-1], os.path.splitext(decomposed_path[i+1])[0]

    def django_sqlmigrate(self, app_name, migration_name):
        git_diff_command = 'cd {0} && python manage.py sqlmigrate {1} {2}'.format(self.location, app_name, migration_name)
        diff_process = Popen(git_diff_command, shell=True, stdout=PIPE, stderr=PIPE)
        sql_statements = []
        for line in diff_process.stdout.readlines():
            if not line.startswith('--'):  # Do not take sql comments into account
                sql_statements.append(line.strip())
        diff_process.wait()
        return sql_statements

    def _test_sql_statement_for_backward_incompatibility(self, sql_statement):
        for test in self.migration_tests:
            if test['fn'](sql_statement):
                return False, test['err_msg']
        return True, None


def valid_folder(folder):
    """Verify folder exists,
    folder is a django project
    and folder is git versioned
    """
    if not os.path.isdir(folder):
        print("The passed argument doesn't seem to be a folder.")
        return False
    django_manage_file = os.path.join(folder, 'manage.py')
    if not os.path.isfile(django_manage_file):
        print("The passed folder doesn't seem to be a django project (no manage.py found).")
        return False
    git_folder = os.path.join(folder, '.git')
    if not os.path.isdir(git_folder):
        print("The passed folder doesn't seem to versioned by git (no .git/ folder found).")
        return False
    return True


def split_path(path):
    a, b = os.path.split(path)
    return (split_path(a) if len(a) > 0 else []) + [b]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Detect backward incompatible django migrations.')
    parser.add_argument('django_folder', metavar='DJANGO_FOLDER', type=str, nargs=1, help='the path to the django project')
    parser.add_argument('commit_id', metavar='GIT_COMMIT_ID', type=str, nargs='?', help='if specified, only migrations since this commit will be taken into account. If not specified, the initial repo commit will be used')
    args = parser.parse_args()

    folder_name = args.django_folder[0]
    if valid_folder(folder_name):
        checker = MigrationChecker(folder_name, args.commit_id)
        checker.check_migrations()
