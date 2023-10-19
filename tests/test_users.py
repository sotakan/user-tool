import unittest

import users

class TestUsers(unittest.TestCase):
    def test_create_google_user(self):
        users.create_google_user("Test", "User", "DKVQUsVD_48qAaA1vw", "integriculture.com")

    def test_get_graph_token(self):
        print(users.get_graph_token())

    def test_create_azure_user(self):
        token = users.get_graph_token()
        res = users.create_azure_user(token, "Test", "User", "DKVQUsVD_48qAaA1vw", "integriculture.net")
        if res != 201:
            unittest.fail("Failed to create user on AzureAD")

    def test_fill_welcome_pdf(self):
        users.fill_welcome_pdf("Test", "User", "DKVQUsVD_48qAaA1vw", "integriculture.com", "integriculture.net", [["","test group"]])

    def test_get_google_groups(self):
        res = users.get_google_groups()
        self.assertEqual(type(res), list)

    def test_add_to_google_group(self):
        res = users.add_to_google_group("noreply@integriculture.com", "john.doe@integriculture.com")